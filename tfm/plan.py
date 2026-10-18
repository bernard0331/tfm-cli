"""Multi-generation projection of your own economy: `tfm plan`.

`tfm value` prices one card at a time against the current tableau. This module plays the rest of the game
forward for you alone, generation by generation, so timing shows up: production bought early pays for
later cards, VP cards can wait, and saving one generation for an expensive card can beat two weak buys.

Each simulated generation:
1. Free conversions: 8 plants → greenery (1 VP, +1 oxygen step while open), 8 heat → temperature step.
2. Plays, greedily by value per M€ out of pocket. Each hand card is priced with `value.value_card` against
   an Outlook built for that generation (gens_left, global parameters, tags and tableau as simulated), and
   only once its requirement is met. Also offered: a flat stream of "average cards" (up to STREAM_CARDS_MAX
   per generation after the current one, each returning what it costs) and standard projects. Nothing is
   played below break-even (PLAY_RATIO) except with money next generation does not need, and in the last
   generation, when leftover M€ is worth nothing.
   Before spending, the plan takes the hand card worth most net of its cost and checks whether playing it
   first (or holding money so next generation's income covers it) projects better than plain greedy order.
3. Production phase (M€ = TR + M€ production; energy becomes heat), then the other players raise the
   global parameters at the table's pace (`Outlook.pace`).

The effects the simulation tracks step by step are production, stock resources, TR, global parameters,
oceans, greeneries, cities, printed VP and VP per tag. Everything else `value_card` prices (actions,
triggers, card draws, bonus steps, ...) is banked at its M€ estimate for the generation the card is played
in and converted at 5 M€ per VP. Tag discounts are applied to the hand cards they discount, and to the
stream of future cards at the deck's rate of matching cards per generation (`deck.matches_per_gen`).

Known limits (read the numbers as a plan, not a forecast):
- Rivals are mostly ignored: they only raise the global parameters at the table pace. No attacks, no
  races for milestones or awards (milestones and awards are left out entirely), no shared VP.
- No board placement: tiles score flat (a city is CITY_VP, an ocean pays OCEAN_ADJACENCY M€), no
  placement bonuses, no adjacency planning. Pathfinders tracks, colonies trading, Turmoil are not simulated.
- Greedy play order with a one-step lookahead (each generation compares "best card first / save for it" with
  greedy for the rest of the game, not every ordering); the game length is fixed at `Outlook.gens_left` and
  does not react to the simulation finishing the parameters early.
- Card actions, draws and triggers are a lump sum at play time, not simulated per generation.
"""
import functools
import itertools

from . import data, deck, value

VP = value.VP

# Assumptions, each derived from the rules or from value.py's own conventions (not fitted to games).
STREAM_CARDS_MAX = 4       # research shows 4 cards per generation: the most average cards one generation can buy
STREAM_RATIO = 1.0         # an average kept card returns what it costs: value.py's break-even reference (Dust Seals),
                           # i.e. M€ the hand does not need still buys VP at value.py's 5 M€ per VP
PLAY_RATIO = 1.0           # play a card only if it returns at least the M€ it costs, until the last generation
CITY_VP = value.CITY_TILE / VP  # a city's greenery adjacency, flat (value.py prices a city tile at 5 M€)
OCEAN_ADJACENCY = value.OCEAN_ADJACENCY  # M€ from ocean adjacency on top of the ocean's TR
PRELUDES_KEPT = 2          # standard Prelude rule: keep 2 of the 4 dealt
RIVAL_VENUS_STEPS = 1.0    # Venus steps per generation from rivals when Venus does not count for game end
MAX = {"temperature": 8, "oxygen": 14, "oceans": 9, "venus": 30}
STEP = {"temperature": 2, "oxygen": 1, "oceans": 1, "venus": 2}
MIN = {"temperature": -30, "oxygen": 0, "oceans": 0, "venus": 0}
STANDARD_PROJECTS = {"Power Plant:SP": 11, "Asteroid:SP": 14, "Aquifer": 18, "Greenery": 23, "City": 25,
                     "Air Scrapping": 15}
SP_LABEL = {"Power Plant:SP": "SP power plant", "Asteroid:SP": "SP asteroid", "Aquifer": "SP aquifer",
            "Greenery": "SP greenery", "City": "SP city", "Air Scrapping": "SP air scrapping"}
STREAM = "avg cards"
# Effects the simulation applies step by step; the rest of a card's value is banked as M€.
MODELLED = ("production", "stock", "tr", "global", "ocean", "greenery", "city")
RESOURCES = ("megacredits", "steel", "titanium", "plants", "energy", "heat")
PROJECT_TYPES = ("automated", "active", "event")


# --------------------------------------------------------------------------------------------- state

class _State:
    """Your economy at the start of one simulated generation's action phase."""

    def __init__(self):
        self.stock = dict.fromkeys(RESOURCES, 0.0)
        self.prod = dict.fromkeys(RESOURCES, 0.0)
        self.tr = 20
        self.tags = {}
        self.tableau = []          # dicts as in the view (name, resources)
        self.hand = []             # card names
        self.params = {}           # temperature °C, oxygen %, oceans, venus % (floats while rivals advance)
        self.cities = 0
        self.greeneries = 0
        self.card_vp = 0.0         # printed VP of cards played in the simulation
        self.banked = 0.0          # M€ estimate of effects not simulated step by step
        self.stream_vp = 0.0
        self.steel_value, self.ti_value = 2.0, 3.0
        self.plays = []            # (generation, label)
        self.reserve = 0.0         # M€ held back this generation (saving)
        self.commit = None         # (generation index, card) to play first
        self.start_cities = 0
        self.trace = []            # (generation, global parameters at the start of its action phase)
        self.stream = {}           # generation → average cards bought (fractions allowed: it is an expectation)

    def copy(self):
        s = _State.__new__(_State)
        s.__dict__.update(self.__dict__)
        for k in ("stock", "prod", "tags", "params", "stream"):
            setattr(s, k, dict(getattr(self, k)))
        for k in ("tableau", "hand", "plays", "trace"):
            setattr(s, k, list(getattr(self, k)))
        return s


class Projection:
    """Result of a simulation: projected final VP, its parts and the play order."""

    def __init__(self, state, start_vp, start_tr, tag_vp, first_gen, gens):
        self.state = state
        self.tr = state.tr
        self.tag_vp = tag_vp
        self.parts = {
            "now": start_vp, "TR gained": state.tr - start_tr, "card VP": state.card_vp + tag_vp,
            "greeneries": state.greeneries, "cities": (state.cities - state.start_cities) * CITY_VP,
            "other effects": state.banked / VP, "average cards": state.stream_vp,
        }
        self.vp = sum(self.parts.values())
        self.first_gen, self.gens = first_gen, gens
        self.plays = state.plays
        self.unplayed = list(state.hand)

    def by_generation(self):
        out = {}
        for gen, label in self.plays:
            out.setdefault(gen, []).append(label)
        return out


def _whole(param, x):
    """A simulated (fractional) parameter as the game shows it: only completed steps count."""
    return MIN[param] + int((x - MIN[param]) / STEP[param] + 1e-9) * STEP[param]


# --------------------------------------------------------------------------------------------- deck shares

def _modules(expansions):
    return frozenset({m for m, on in expansions.items() if on} | {"base", "corpera", "promo"})


@functools.lru_cache(maxsize=None)
def _project_cards(modules):
    return tuple(c for c in data.cards().values() if c.get("type") in PROJECT_TYPES and c.get("module") in modules)


def mean_cost(expansions):
    """Average printed cost of a project card in this game's deck (from the card data)."""
    cards = _project_cards(_modules(expansions))
    return sum(c.get("cost") or 0 for c in cards) / len(cards) if cards else 12.0


def _tag_share(expansions, tag, events=False):
    """Share of the deck's project cards with a tag (events count only for payment, not for tag effects)."""
    return _share(_modules(expansions), tag, events)


@functools.lru_cache(maxsize=None)
def _share(modules, tag, events):
    cards = _project_cards(modules)
    hits = sum(1 for c in cards if tag in (c.get("tags") or []) and (events or c.get("type") != "event"))
    return hits / len(cards) if cards else 0.0


def stream_matches(ctx, tag):
    """Expected plays with a tag among one generation's drawn cards (not yet in hand), from the deck's
    composition (tfm/deck.py). Simulated generations start with an empty hand, so this generation's draws count
    too, the last one included: the per-generation rate, not value.future_matches (which covers only the
    generations after this one)."""
    return deck.matches_per_gen(ctx, f"tag:{tag}")


# --------------------------------------------------------------------------------------------- planner

class _Planner:
    def __init__(self, view, gens=None):
        self.view = view
        base = value.Outlook(view, gens_left=gens)
        self.base = base
        self.gens = base.gens_left
        self.first_gen = base.generation
        self.n_players = len(base.players)
        # Rivals' share of the table's terraforming pace (steps per generation).
        self.rival_pace = 0.0 if self.n_players == 1 else base.pace * (self.n_players - 1) / self.n_players
        self.venus_on = bool(base.expansions.get("venus"))
        self.venus_counts = base.venus_counts
        self.mean_cost = mean_cost(base.expansions)
        self.building_share = _tag_share(base.expansions, "building", events=True)
        self.space_share = _tag_share(base.expansions, "space", events=True)
        self._cache = {}

    # ---- contexts

    def ctx(self, s, i):
        """An Outlook for simulated generation i (0 = the current one)."""
        g0 = self.view["game"]
        p = s.params
        whole = {k: _whole(k, x) for k, x in p.items()}
        game = dict(g0, generation=self.first_gen + i, temperature=whole["temperature"],
                    oxygenLevel=whole["oxygen"], oceans=whole["oceans"], venusScaleLevel=whole["venus"],
                    milestones=[], awards=[], pathfinders=None)
        me0 = self.view["thisPlayer"]
        me = dict(me0, tags=s.tags, tableau=s.tableau, terraformRating=s.tr, citiesCount=s.cities,
                  steelValue=s.steel_value, titaniumValue=s.ti_value)
        players = [me if q["color"] == me0["color"] else q for q in self.view["players"]]
        return value.Outlook({"thisPlayer": me, "players": players, "game": game, "cardsInHand": []},
                             gens_left=self.gens - i)

    def valuation(self, name, s, i, ctx):
        key = (name, i, tuple(_whole(k, x) for k, x in s.params.items()), s.tr, s.cities,
               tuple(sorted(s.tags.items())), tuple(c["name"] for c in s.tableau))
        hit = self._cache.get(key)
        if hit is None:
            v = value.value_card(name, ctx)
            hit = self._cache[key] = (v.value, v.value - self._modelled(name, v, ctx))
        return hit

    @staticmethod
    def _modelled(name, v, ctx):
        """M€ value.py gives the effects this simulation applies itself (subtracted to leave the residual)."""
        beh = data.behavior(name) or ({"behavior": value.STANDARD_BEHAVIORS[name]}
                                      if name in value.STANDARD_BEHAVIORS else {})
        tags = v.persistent_tags
        trial = value.Valuation(name)
        for key in ("behavior", "firstAction"):
            part = {k: x for k, x in (beh.get(key) or {}).items() if k in MODELLED}
            value._apply(part, trial, ctx, tags, name)
        out = trial.value
        info = v.info or {}
        if info.get("type") in ("corporation", "prelude") and info.get("startingMC"):
            out += info["startingMC"]
        vp = beh.get("vp")
        if isinstance(vp, (int, float)):
            out += vp * VP
        elif isinstance(vp, dict) and "tag" in vp:
            out += (value._resolve({"tag": vp["tag"]}, tags, ctx) // (vp.get("per") or 1)) * VP
        # Discounts are applied by the simulation (hand cards and the future-card stream), so value.py's
        # discount on future draws (in v.combo) is not banked as well.
        out += sum(amt for label, amt in v.parts + v.combo if label.startswith("discount "))
        return out

    # ---- costs and requirements

    def discount(self, s, tags):
        total = 0
        for c in s.tableau:
            d = (data.behavior(c["name"]) or {}).get("cardDiscount")
            for one in (d if isinstance(d, list) else [d]) if d else []:
                if not one.get("tag") or one["tag"] in tags:
                    total += one.get("amount", 0)
        return total

    def card_cost(self, name, s):
        """(M€ out of pocket, steel used, titanium used) to play a hand card now."""
        info = data.card(name) or {}
        tags = info.get("tags") or []
        cost = max(0, (info.get("cost") or 0) - self.discount(s, tags))
        steel = ti = 0
        if "space" in tags and s.ti_value:
            ti = min(int(s.stock["titanium"]), int(cost // s.ti_value))
            cost -= ti * s.ti_value
        if "building" in tags and s.steel_value:
            steel = min(int(s.stock["steel"]), int(cost // s.steel_value))
            cost -= steel * s.steel_value
        return cost, steel, ti

    def stream_cost(self, s):
        """(M€ out of pocket, steel, titanium) for one average card: steel and titanium pay for the
        deck's share of building and space cards."""
        cost = max(0.0, self.mean_cost - self.discount(s, ()))
        ti = min(s.stock["titanium"], self.space_share * cost / s.ti_value) if s.ti_value else 0.0
        steel = min(s.stock["steel"], self.building_share * cost / s.steel_value) if s.steel_value else 0.0
        return cost - ti * s.ti_value - steel * s.steel_value + value.BUY_COST, steel, ti

    def playable(self, name, s, ctx):
        info = data.card(name) or {}
        for req in info.get("req", []):
            met, _ = value.requirement_status(req, ctx)
            if met is False:
                return False
        prod = ((data.behavior(name) or {}).get("behavior") or {}).get("production") or {}
        for res, amt in prod.items():
            n = value._resolve(amt, info.get("tags") or [], ctx)
            floor = -5 if res == "megacredits" else 0
            if s.prod.get(res, 0) + n < floor:
                return False
        return True

    # ---- effects

    def raise_param(self, s, param, steps):
        """Raise a global parameter by whole steps for you; returns the TR gained."""
        if param not in s.params or (param == "venus" and not self.venus_on):
            return 0
        room = int(round((MAX[param] - _whole(param, s.params[param])) / STEP[param]))
        done = max(0, min(int(steps), room))
        s.params[param] = min(MAX[param], s.params[param] + done * STEP[param])
        s.tr += done
        return done

    def apply(self, name, s, ctx, residual):
        info = data.card(name) or {}
        beh = data.behavior(name) or ({"behavior": value.STANDARD_BEHAVIORS[name]}
                                      if name in value.STANDARD_BEHAVIORS else {})
        ctype = info.get("type")
        persistent = [] if ctype == "event" else (info.get("tags") or [])
        for key in ("behavior", "firstAction"):
            b = beh.get(key) or {}
            for res, amt in (b.get("production") or {}).items():
                if res in s.prod:
                    s.prod[res] += value._resolve(amt, persistent, ctx)
            for res, amt in (b.get("stock") or {}).items():
                if res in s.stock:
                    s.stock[res] += value._resolve(amt, persistent, ctx)
            if "tr" in b:
                s.tr += value._resolve(b["tr"], persistent, ctx)
            for param, steps in (b.get("global") or {}).items():
                if steps > 0:
                    self.raise_param(s, param, steps)
            if "ocean" in b:
                n = b["ocean"].get("count", 1) if isinstance(b["ocean"], dict) else 1
                placed = self.raise_param(s, "oceans", n)
                s.stock["megacredits"] += placed * OCEAN_ADJACENCY
            if "greenery" in b:
                s.greeneries += 1
                self.raise_param(s, "oxygen", 1)
            if "city" in b:
                s.cities += 1
        if ctype in ("corporation", "prelude") and info.get("startingMC"):
            s.stock["megacredits"] += info["startingMC"]
        vp = beh.get("vp")
        if isinstance(vp, (int, float)):
            s.card_vp += vp
        if ctype != "event" and name not in value.STANDARD_BEHAVIORS:
            for t in persistent:
                s.tags[t] = s.tags.get(t, 0) + 1
            s.tableau.append({"name": name, "resources": 0})
        if beh.get("behavior", {}).get("steelValue"):
            s.steel_value += beh["behavior"]["steelValue"]
        if beh.get("behavior", {}).get("titaniumValue"):
            s.ti_value += beh["behavior"]["titaniumValue"]
        s.banked += residual

    def convert(self, s, gen):
        while s.stock["plants"] >= 8:
            s.stock["plants"] -= 8
            s.greeneries += 1
            self.raise_param(s, "oxygen", 1)
            s.plays.append((gen, "greenery (plants)"))
        while s.stock["heat"] >= 8 and s.params["temperature"] < MAX["temperature"]:
            s.stock["heat"] -= 8
            self.raise_param(s, "temperature", 1)
            s.plays.append((gen, "temperature (heat)"))

    def production(self, s):
        s.stock["heat"] += s.stock["energy"]
        s.stock["energy"] = 0
        s.stock["megacredits"] += s.tr
        for res in RESOURCES:
            s.stock[res] += s.prod[res]

    def rivals(self, s):
        """Other players raise the global parameters at their share of the table pace."""
        params = ["temperature", "oxygen", "oceans"] + (["venus"] if self.venus_counts else [])
        left = {p: max(0.0, (MAX[p] - s.params[p]) / STEP[p]) for p in params}
        total = sum(left.values())
        if total:
            for p in params:
                s.params[p] = min(MAX[p], s.params[p] + min(left[p], self.rival_pace * left[p] / total) * STEP[p])
        if self.venus_on and not self.venus_counts:
            s.params["venus"] = min(MAX["venus"], s.params["venus"] + RIVAL_VENUS_STEPS * STEP["venus"])

    # ---- one generation

    def options(self, s, i, ctx):
        """Hand cards, standard projects and stream cards on offer: (ratio, kind, name, value, residual, cost)."""
        out = []
        for name in s.hand:
            if not self.playable(name, s, ctx):
                continue
            total, residual = self.valuation(name, s, i, ctx)
            cost = self.card_cost(name, s)[0]
            out.append((total / max(1.0, cost), "card", name, total, residual, cost))
        out += self.sp_options(s, i, ctx)
        if i > 0:
            cost = self.stream_cost(s)[0]
            ratio = STREAM_RATIO * (self.mean_cost + value.BUY_COST) / max(1.0, cost)
            for _ in range(STREAM_CARDS_MAX):
                out.append((ratio, "stream", STREAM, ratio * cost, 0.0, cost))
        out.sort(key=lambda o: -o[0])
        return out

    def focus(self, s, i, opts):
        """The hand card worth most net of its cost, as (M€ to hold back now, (generation index, card)) when
        greedy-by-ratio might not play it first: play it first if affordable now, else save for it if next
        generation's income covers it."""
        cards = [o for o in opts if o[1] == "card" and o[0] >= PLAY_RATIO]
        if not cards:
            return None
        ratio, _, name, total, _, cost = max(cards, key=lambda o: o[3] - o[5])
        if cost <= s.stock["megacredits"]:
            return None if cards[0][2] == name else (0.0, (i, name))
        income = s.tr + s.prod["megacredits"]
        if i + 1 < self.gens and cost <= s.stock["megacredits"] + income:
            return max(0.0, cost - income), (i + 1, name)
        return None

    def generation(self, s, i, branch):
        gen = self.first_gen + i
        last = i == self.gens - 1
        ctx = self.ctx(s, i)
        s.trace.append((gen, dict(s.params)))
        self.convert(s, gen)
        if i > 0:
            # Tag discounts also apply to the cards you will draw (general ones are in the average card's cost).
            for c in s.tableau:
                d = (data.behavior(c["name"]) or {}).get("cardDiscount")
                for one in (d if isinstance(d, list) else [d]) if d else []:
                    if one.get("tag"):
                        s.stock["megacredits"] += one.get("amount", 0) * stream_matches(ctx, one["tag"])
        opts = self.options(s, i, ctx)
        if branch and not last:
            target = self.focus(s, i, opts)
            if target:
                reserve, commit = target
                saver = s.copy()
                saver.reserve, saver.commit = reserve, commit
                if self.finish(saver, i, opts).vp > self.finish(s.copy(), i, opts).vp:
                    s.reserve, s.commit = reserve, commit
        self.spend(s, i, ctx, opts, last)
        s.reserve = 0.0
        self.production(s)
        self.rivals(s)

    def spend(self, s, i, ctx, opts, last):
        if s.commit and s.commit[0] == i:
            name = s.commit[1]
            s.commit = None
            hit = [o for o in opts if o[1] == "card" and o[2] == name]
            if hit:
                opts = hit + [o for o in opts if o is not hit[0]]
        ctx = self.buy(s, i, ctx, opts, 0.0 if last else PLAY_RATIO, s.reserve)
        if not last:
            # M€ that next generation's income does not need for its average cards would otherwise sit until
            # the last generation, when a standard project is worth least: spend it on one now.
            need = STREAM_CARDS_MAX * self.stream_cost(s)[0] - (s.tr + s.prod["megacredits"])
            self.buy(s, i, ctx, self.sp_options(s, i, ctx), 0.0, s.reserve + max(0.0, need))

    def sp_options(self, s, i, ctx):
        out = []
        for name, cost in STANDARD_PROJECTS.items():
            if name == "Air Scrapping" and not self.venus_on:
                continue
            total, residual = self.valuation(name, s, i, ctx)
            if total > 0:
                out.append((total / cost, "sp", name, total, residual, cost))
        return sorted(out, key=lambda o: -o[0])

    def buy(self, s, i, ctx, opts, floor, keep):
        """Play options in order while each returns at least `floor` per M€ and leaves `keep` M€."""
        gen = self.first_gen + i
        for ratio, kind, name, total, residual, _ in opts:
            if ratio < floor or total <= 0:
                continue
            while True:
                if kind == "card":
                    if name not in s.hand or not self.playable(name, s, ctx):
                        break
                    cost, steel, ti = self.card_cost(name, s)
                elif kind == "sp":
                    cost, steel, ti = STANDARD_PROJECTS[name], 0, 0
                else:
                    cost, steel, ti = self.stream_cost(s)
                money = s.stock["megacredits"] - keep
                if kind == "stream":
                    share = min(1.0, money / cost) if cost > 0 else 1.0
                    if share <= 1e-6:
                        break
                    s.stock["megacredits"] -= share * cost
                    s.stock["steel"] -= share * steel
                    s.stock["titanium"] -= share * ti
                    s.stream_vp += share * total / VP
                    if gen not in s.stream:
                        s.plays.append((gen, STREAM))
                    s.stream[gen] = s.stream.get(gen, 0.0) + share
                    break
                if cost > money + 1e-9:
                    break
                s.stock["megacredits"] -= cost
                s.stock["steel"] -= steel
                s.stock["titanium"] -= ti
                if kind == "card":
                    s.hand.remove(name)
                self.apply(name, s, ctx, residual)
                s.plays.append((gen, SP_LABEL.get(name, name)))
                ctx = self.ctx(s, i)
                if kind != "sp":
                    break
                # Re-price a repeated standard project once its parameter moves.
                total, residual = self.valuation(name, s, i, ctx)
                if total <= 0 or total / STANDARD_PROJECTS[name] < floor:
                    break
        return ctx

    def finish(self, s, i, opts=None):
        """Play out generation i (already priced as opts) and the rest greedily, without further saving branches."""
        ctx = self.ctx(s, i)
        last = i == self.gens - 1
        self.spend(s, i, ctx, opts if opts is not None else self.options(s, i, ctx), last)
        s.reserve = 0.0
        self.production(s)
        self.rivals(s)
        for j in range(i + 1, self.gens):
            self.generation(s, j, branch=False)
        return self.result(s)

    def run(self, s, branch=True):
        for i in range(self.gens):
            self.generation(s, i, branch)
        return self.result(s)

    def result(self, s):
        # Plants left after the final production phase still become greeneries.
        s = s.copy()
        while s.stock["plants"] >= 8:
            s.stock["plants"] -= 8
            s.greeneries += 1
            self.raise_param(s, "oxygen", 1)
        tag_vp = 0.0
        for c in s.tableau:
            vp = (data.behavior(c["name"]) or {}).get("vp")
            if isinstance(vp, dict) and "tag" in vp:
                tags = vp["tag"] if isinstance(vp["tag"], list) else [vp["tag"]]
                per = vp.get("per") or 1
                final = sum(s.tags.get(t, 0) for t in tags) + s.tags.get("wild", 0)
                start = self.start_tag_counts.get(c["name"])
                tag_vp += final // per - (start // per if start is not None else 0)
        return Projection(s, self.start_vp, self.start_tr, tag_vp, self.first_gen, self.gens)

    # ---- starting states

    def state_from_view(self, extra=(), without=()):
        me = self.view["thisPlayer"]
        g = self.view["game"]
        s = _State()
        for res in RESOURCES:
            key = "megaCredits" if res == "megacredits" else res
            s.stock[res] = float(me.get(key, 0) or 0)
            prod_key = "megacreditProduction" if res == "megacredits" else f"{res}Production"
            s.prod[res] = float(me.get(prod_key, 0) or 0)
        s.tr = me.get("terraformRating", 20)
        s.tags = dict(me.get("tags") or {})
        s.tableau = list(me.get("tableau") or [])
        s.cities = s.start_cities = me.get("citiesCount", 0) or 0
        s.steel_value = float(me.get("steelValue", 2))
        s.ti_value = float(me.get("titaniumValue", 3))
        s.params = {"temperature": float(g["temperature"]), "oxygen": float(g["oxygenLevel"]),
                    "oceans": float(g["oceans"]), "venus": float(g.get("venusScaleLevel", 0) or 0)}
        hand = [c["name"] for c in (self.view.get("cardsInHand") or []) + (self.view.get("preludeCardsInHand") or [])]
        drop = set(without or ())
        s.hand = [n for n in hand if n not in drop] + [data.card_name(n) or n for n in extra or ()]
        self.start_tr = s.tr
        self.start_vp = (me.get("victoryPointsBreakdown") or {}).get("total", s.tr)
        self._remember_tags(s)
        return s

    def _remember_tags(self, s):
        self.start_tag_counts = {}
        for c in s.tableau:
            vp = (data.behavior(c["name"]) or {}).get("vp")
            if isinstance(vp, dict) and "tag" in vp:
                tags = vp["tag"] if isinstance(vp["tag"], list) else [vp["tag"]]
                self.start_tag_counts[c["name"]] = sum(s.tags.get(t, 0) for t in tags) + s.tags.get("wild", 0)


# --------------------------------------------------------------------------------------------- public API

def project(view, extra=None, without=None, gens=None, mc=0):
    """Projected final VP and play order for your own economy. `extra` adds cards to the hand, `without`
    removes hand cards, `mc` adjusts starting M€ (e.g. -3 to buy a card)."""
    planner = _Planner(view, gens)
    s = planner.state_from_view(extra, without)
    s.stock["megacredits"] += mc
    return planner.run(s)


def decision_value(view, name, buying=False, gens=None):
    """VP a card adds to the projection: projected VP with it minus without it."""
    key = data.card_name(name) or name
    hand = {c["name"] for c in view.get("cardsInHand") or []}
    if key in hand:
        return project(view, gens=gens).vp - project(view, without=[key], gens=gens).vp
    with_it = project(view, extra=[key], gens=gens, mc=-value.BUY_COST if buying else 0)
    return with_it.vp - project(view, gens=gens).vp


def opening(view, corporation, preludes=(), keep=(), gens=None, free=False):
    """Score an opening bundle (corporation + preludes + kept project cards) by projected final VP.

    Starts from generation 1 with the game's starting parameters and 20 TR (14 solo), the corporation's
    starting M€ minus 3 M€ per kept card (none if `free`), plays the corporation's and preludes' effects,
    then simulates the game."""
    planner = _Planner(view, gens)
    g = view["game"]
    s = _State()
    s.tr = 14 if planner.n_players == 1 else 20
    s.params = {"temperature": float(g["temperature"]), "oxygen": float(g["oxygenLevel"]),
                "oceans": float(g["oceans"]), "venus": float(g.get("venusScaleLevel", 0) or 0)}
    planner.start_tr, planner.start_vp = s.tr, s.tr
    planner._remember_tags(s)
    s.hand = [data.card_name(n) or n for n in keep]
    for name in [corporation] + list(preludes):
        name = data.card_name(name) or name
        ctx = planner.ctx(s, 0)
        _, residual = planner.valuation(name, s, 0, ctx)
        planner.apply(name, s, ctx, residual)
        s.plays.append((planner.first_gen, name))
    if not free:
        s.stock["megacredits"] -= value.BUY_COST * len(s.hand)
    return planner.run(s)


def opening_cards(view):
    """Corporations, preludes and project cards on offer in the opening decision."""
    found = {}

    def walk(node):
        if isinstance(node, dict):
            for c in node.get("cards") or []:
                if isinstance(c, dict) and c.get("name"):
                    found.setdefault(c["name"], None)
            for key in ("options", "andOptions"):
                for child in node.get(key) or []:
                    walk(child)
    walk(view.get("waitingFor"))
    for key in ("dealtCorporationCards", "dealtPreludeCards", "dealtProjectCards"):
        for c in view.get(key) or []:
            found.setdefault(c["name"], None)
    out = {"corporation": [], "prelude": [], "project": []}
    for name in found:
        t = (data.card(name) or {}).get("type")
        out["corporation" if t == "corporation" else "prelude" if t == "prelude" else "project"].append(name)
    return out


def best_openings(view, cards=None, gens=None, top=3):
    """Rank corporation × prelude-pair bundles: [(Projection, corporation, preludes, kept cards)].

    The kept hand for each bundle is the cards its plan plays when every offered project card is free;
    the bundle is then rescored paying 3 M€ per kept card."""
    cards = cards or opening_cards(view)
    pres = cards["prelude"]
    pairs = list(itertools.combinations(pres, min(PRELUDES_KEPT, len(pres)))) or [()]
    ranked = []
    for corp in cards["corporation"]:
        for pair in pairs:
            trial = opening(view, corp, pair, cards["project"], gens, free=True)
            played = {label for _, label in trial.plays}
            keep = [n for n in cards["project"] if n in played]
            ranked.append((opening(view, corp, pair, keep, gens), corp, pair, keep))
    ranked.sort(key=lambda r: -r[0].vp)
    return ranked[:top] if top else ranked


# --------------------------------------------------------------------------------------------- output

def describe(p, limit=None):
    """Compact lines: projected VP with its main parts, then the play order by generation."""
    parts = " · ".join(f"{k} {v:+.0f}" if k != "now" else f"now {v:.0f}" for k, v in p.parts.items() if round(v))
    last = p.first_gen + p.gens - 1
    lines = [f"PLAN: ~{p.vp:.0f} VP at the end of generation {last} ({parts}); rivals ignored, greedy order"]
    for gen, labels in sorted(p.by_generation().items()):
        counted = []
        for label in labels:
            if label == STREAM:
                label = f"{STREAM} ×{p.state.stream[gen]:.1f}"
            if counted and counted[-1][0] == label:
                counted[-1][1] += 1
            else:
                counted.append([label, 1])
        lines.append(f"  gen {gen}: " + ", ".join(f"{label}" + (f" ×{n}" if n > 1 else "") for label, n in counted))
    if p.unplayed:
        lines.append("  never played: " + ", ".join(p.unplayed))
    return lines[:limit] if limit else lines
