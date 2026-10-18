"""Rough card valuation for decision making: `tfm value`.

Two layers:

1. A **baseline number**. Every effect a card declares (production, resources, TR, global steps, tiles,
   cards, VP) is priced in M€ (1 VP = 5 M€; 1 TR = 5 M€ + 1 M€ per remaining spendable production
   phase; see docs/STRATEGY.md §6), with production counted only for the production phases the game is likely to
   have left. Compare it with what you pay (play cost, plus 3 M€ to buy a card you don't own yet).
2. **Context checks** on the live game. The card's steps, tiles and tags run through one event queue
   (_Sim), so chains are followed: global-parameter bonus thresholds (oxygen 8% → temperature → 0°C ocean),
   Pathfinders planetary-track rewards (for you and for everyone, including rewards that raise a
   parameter), the last step of a parameter, and what your own cards' triggers pay (OWN_TRIGGERS). Also:
   milestones it would let you claim, award positions it changes for you and for rivals, requirements it
   meets for cards in your hand, rivals' cards that pay out when you do this, and attacks a rival can block.
3. **Combos with the hand** (planned tableau). Hand cards count as future plays, each with a chance of being
   played before the end. Effects that depend on future plays (this card's OWN_TRIGGERS effect, discounts,
   VP per tag) are priced from those chances, hand effect cards this card would fire get partial credit,
   and requirements it meets for hand cards are priced by how much earlier they can be played. All of it
   is the card's marginal value to the planned set, printed on one `combo` line.

The numbers are estimates for comparing options, not exact values. Effects the app implements with
custom code are flagged so you read the card text yourself.
"""
import math
import random
import re
from collections import deque

from . import data, deck

VP, CARD, BUY_COST = 5.0, 3.5, 3
CITY_TILE, SPECIAL_TILE, COLONY = 5.0, 2.0, 10.0
OCEAN_ADJACENCY = 2.0   # typical ocean-adjacency income on top of the ocean's TR
PLANETARY = ("venus", "earth", "mars", "jovian", "moon")

# Underworld token bag (normal game, from the app's UnderworldExpansion.TOKEN_COUNTS).
TOKEN_COUNTS = {
    "nothing": 5, "corruption1": 13, "corruption2": 2, "card1": 4, "card2": 1, "mcprod1pertemp": 2,
    "steel2plant": 2, "steel1production": 4, "steel2pertemp": 3, "titaniumandplant": 3, "titanium2": 3,
    "titanium1production": 1, "titanium1pertemp": 3, "plant2": 4, "plant3": 1, "plant1production": 4,
    "plant2pertemp": 3, "energy2": 2, "energy1production": 5, "heat2production": 3, "microbe2": 4,
    "microbe2pertemp": 1, "tr": 2, "ocean": 2, "sciencetag": 2, "planttag": 2, "anyresource1": 2, "place6mc": 2,
    "oceanrequirementmod": 2, "oxygenrequirementmod": 2, "temprequirementmod": 2,
}

# Standard projects and actions are implemented in code in the app, so their effects are spelled out here.
STANDARD_BEHAVIORS = {
    "Aquifer": {"ocean": {}},
    "City": {"city": {}, "production": {"megacredits": 1}},
    "Power Plant:SP": {"production": {"energy": 1}},
    "Greenery": {"greenery": {}},
    "Asteroid:SP": {"global": {"temperature": 1}},
    "Air Scrapping": {"global": {"venus": 1}},
    "Air Scrapping (Var)": {"global": {"venus": 1}},
    "Build Colony": {"colonies": {"buildColony": {}}},
    "Buffer Gas": {"tr": 1},
    "Excavate:SP": {"underworld": {"excavate": 1}},
    # Conversions spend plants/heat that have no better use, so only the gain is priced.
    "Convert Plants": {"greenery": {}},
    "Convert Heat": {"global": {"temperature": 1}},
}

# Cards whose TR depends on your tags are custom code in the app, so their count is spelled out here.
TR_PER_TAG = {
    "Terraforming Ganymede": {"tag": "jovian"},
    "Social Events": {"tag": "mars", "per": 2},
}

# Well-known cards that pay their owner (or the acting player) when ANY player does something.
ANY_PLAYER_TRIGGERS = {
    "Aphrodite": ("venus", "its owner gains 2 M€ per Venus step"),
    "Exploitation Of Venus": ("venus", "the player raising Venus gains 2 M€ per step"),
    "Poseidon": ("colony", "its owner gains 1 M€ production per colony"),
    "Botanical Experience": ("greenery", "its owner gains 1 data per greenery (3 data = +1 plant production)"),
    "Tharsis Republic": ("city", "its owner gains 1 M€ production per city on Mars"),
    "Rover Construction": ("city", "its owner gains 2 M€ per city"),
    "Pets": ("city", "its owner adds an animal (1/2 VP) per city"),
    "Immigrant City": ("city", "its owner gains 1 M€ production per city"),
    "Arctic Algae": ("ocean", "its owner gains 2 plants per ocean"),
    "Saturn Systems": ("jovian", "its owner gains 1 M€ production per Jovian tag"),
    "Splice": ("microbe", "its owner gains 2 M€ per microbe tag"),
}


# --------------------------------------------------------------------------------------------- outlook

class Outlook:
    """What the current game state says about time left and what resources are worth."""

    def __init__(self, view, gens_left=None):
        g = view["game"]
        self.view = view
        self.game = g
        self.me = view["thisPlayer"]
        self.players = view["players"]
        self.rivals = [p for p in self.players if p["color"] != self.me["color"]]
        self.names = {p["color"]: p["name"] for p in self.players}
        opts = g["gameOptions"]
        self.expansions = opts.get("expansions", {})
        self.alt_venus = bool(opts.get("altVenusBoard"))
        self.venus_counts = bool(self.expansions.get("venus")) and bool(opts.get("requiresVenusTrackCompletion"))
        self.generation = g["generation"]
        self.temp, self.oxygen, self.oceans = g["temperature"], g["oxygenLevel"], g["oceans"]
        self.venus = g.get("venusScaleLevel", 0) or 0
        self.left = {
            "temperature": max(0, (8 - self.temp) // 2),
            "oxygen": max(0, 14 - self.oxygen),
            "oceans": max(0, 9 - self.oceans),
            "venus": max(0, (30 - self.venus) // 2) if self.expansions.get("venus") else 0,
        }
        remaining = self.left["temperature"] + self.left["oxygen"] + self.left["oceans"] + \
            (self.left["venus"] if self.venus_counts else 0)
        self.pace = self._pace(g.get("globalsPerGeneration") or [])
        by_pace = 1 if remaining == 0 else max(1, math.ceil(remaining / self.pace))
        # Early pace understates how fast tables finish (terraforming accelerates), so also cap the
        # estimate at a typical game length for this player count and setup. Our 4-player games with
        # Prelude ended in generation 8 and our 5-player ones in generation 7.
        typical = {1: 14, 2: 12, 3: 11, 4: 9}.get(len(self.players), 8) - (1 if self.expansions.get("prelude") else 0)
        by_length = max(1, typical - self.generation + 1)
        self.gens_left = gens_left if gens_left is not None else min(by_pace, by_length)
        self.by_pace, self.by_length = by_pace, by_length
        # Production at the end of each remaining generation except the last can still be spent.
        self.phases = max(0, self.gens_left - 1)
        # A TR is 1 VP at the end plus 1 M€ of income at every remaining spendable production phase.
        self.tr = VP + self.phases
        self.plant_phases = self.gens_left  # final plants still become a greenery
        self.remaining_steps = remaining
        # 8 heat = 1 temperature TR; 8 plants = a greenery (1 VP, plus 1 oxygen TR while oxygen is open).
        # Ambient keeps turning 8 heat into 1 TR after temperature is maxed.
        ambient = any(c["name"] == "Ambient" for c in self.me.get("tableau") or [])
        self.heat = self.tr / 8 if self.left["temperature"] or ambient else 0.0
        self.plant = (VP + self.tr) / 8 if self.left["oxygen"] else VP / 8
        self.steel = float(self.me.get("steelValue", 2))
        self.titanium = float(self.me.get("titaniumValue", 3))
        self.energy = 1.0
        self.tags = dict(self.me.get("tags") or {})
        self.hand = view.get("cardsInHand") or []
        self.tableau = {c["name"]: c for c in self.me.get("tableau", [])}

    def greeneries(self, color=None):
        return sum(1 for s in self.game.get("spaces", []) if s.get("tileType") is not None
                   and data.tile_name(s["tileType"]) == "greenery" and (color is None or s.get("color") == color))

    def _pace(self, history):
        def steps(e):
            s = max(0, (e.get("temperature", -30) + 30) // 2) + e.get("oxygen", 0) + e.get("oceans", 0)
            if self.venus_counts:
                s += max(0, e.get("venus", 0) // 2)
            return s
        if len(history) >= 2:
            recent = history[-3:]
            per_gen = (steps(recent[-1]) - steps(recent[0])) / (len(recent) - 1)
            if per_gen > 0:
                return per_gen
        return 5.0  # typical 4-player pace when there is no history yet

    def summary(self):
        return (f"OUTLOOK: generation {self.generation}, about {self.gens_left} generation(s) left including this one "
                f"({self.remaining_steps} terraforming steps remain at ~{self.pace:.1f}/generation → {self.by_pace}; "
                f"typical game length → {self.by_length}; override with --gens) → "
                f"{self.phases} spendable production phase(s). Rates: VP {VP:g}, TR {self.tr:g}, heat {self.heat:g}, "
                f"plant {self.plant:g}, steel {self.steel:g}, Ti {self.titanium:g}, card {CARD:g} M€.")


# --------------------------------------------------------------------------------------------- valuation

class Valuation:
    def __init__(self, name):
        self.name = name
        self.value = 0.0
        self.parts = []      # (label, M€)
        self.flags = []      # context notes
        self.manual = []     # things the numbers don't cover
        self.raises = {"temperature": 0, "oxygen": 0, "venus": 0, "oceans": 0}
        self.tiles = {"city": 0, "greenery": 0, "ocean": 0, "other": 0}
        self.prod = {}       # production change by resource
        self.stock = {}
        self.tr = 0.0
        self.colonies = 0
        self.draws = 0
        self.card_resources = 0
        self.tokens = 0      # underground tokens claimed (Tunneler, Excavator)
        self.attack = False
        self.combo = []      # (label, M€) priced from the planned tableau; printed on one line

    def add(self, label, amount):
        if amount:
            self.value += amount
            self.parts.append((label, amount))

    def add_combo(self, label, amount, keep=False):
        if amount or keep:
            self.value += amount
            self.combo.append((label, amount))


def _resolve(count, card_tags, ctx):
    """Evaluate a Countable (a number, or a dict such as {"tag": "jovian", "per": 2})."""
    if count is None:
        return 0
    if isinstance(count, (int, float)):
        return count
    total = 0
    if "tag" in count:
        tags = count["tag"] if isinstance(count["tag"], list) else [count["tag"]]
        if count.get("all") or count.get("others"):
            players = ctx.rivals if count.get("others") else ctx.players
            total += sum((p.get("tags") or {}).get(t, 0) for p in players for t in tags)
        else:
            total += sum(ctx.tags.get(t, 0) for t in tags) + ctx.tags.get("wild", 0) + sum(card_tags.count(t) for t in tags)
    # As in the app, cities and greeneries count every player's tiles unless `all` is false.
    if "cities" in count:
        total += ctx.me["citiesCount"] if count.get("all") is False else sum(p["citiesCount"] for p in ctx.players)
    if "greeneries" in count:
        total += ctx.greeneries(None if count.get("all") is not False else ctx.me["color"])
    if "oceans" in count:
        total += ctx.oceans
    if "colonies" in count:
        total += sum(p["coloniesCount"] for p in ctx.players) if count.get("all") else ctx.me["coloniesCount"]
    total *= count.get("each", 1)
    if count.get("per"):
        total //= count["per"]
    return total


def _unit(res, ctx):
    return {"megacredits": 1.0, "steel": ctx.steel, "titanium": ctx.titanium, "plants": ctx.plant,
            "energy": ctx.energy, "heat": ctx.heat}.get(res, 1.0)


def _resource_vp_value(card_name, ctx, resource_type=None):
    """M€ value of one resource placed on a card, from that card's VP rule."""
    beh = data.behavior(card_name) or {}
    vp = beh.get("vp")
    if isinstance(vp, dict) and "resourcesHere" in vp:
        per = vp.get("per") or (vp["resourcesHere"] if isinstance(vp["resourcesHere"], int) else 1) or 1
        return VP / per
    return 0.5


def _best_target(ctx, resource_type, exclude=None, this_card=None):
    best, best_name = 0.5, None
    candidates = list(ctx.tableau) + ([this_card] if this_card and this_card not in ctx.tableau else [])
    for name in candidates:
        if name == exclude:
            continue
        info = data.card(name) or {}
        if resource_type and info.get("resource") != resource_type:
            continue
        if not resource_type and not info.get("resource"):
            continue
        v = _resource_vp_value(name, ctx)
        if v > best:
            best, best_name = v, name
    return best, best_name


def _apply(beh, v, ctx, card_tags, card_name, scale=1.0, label=""):
    """Price one Behavior dict into v. `scale` > 1 for repeated actions."""
    if not beh:
        return
    pre = f"{label}" if label else ""
    if "or" in beh:
        best = None
        for option in beh["or"].get("behaviors", []):
            trial = Valuation(card_name)
            _apply(option, trial, ctx, card_tags, card_name)
            if best is None or trial.value > best.value:
                best = trial
        if best:
            v.add(pre + "best option", best.value * scale)
            v.raises = {k: v.raises[k] + best.raises[k] * scale for k in v.raises}
    for key in ("spend", "lose"):
        if key in beh:
            spend = beh[key]
            if key == "lose":
                spend = spend.get("stock") or spend.get("production") or {}
            for res, amt in spend.items():
                if res in ("canUseSteel", "canUseTitanium"):
                    continue
                n = _resolve(amt, card_tags, ctx)
                if res == "resourcesHere":
                    continue
                cost = n * (_unit(res, ctx) if res in ("megacredits", "steel", "titanium", "plants", "energy", "heat") else 1.0)
                v.add(f"{pre}spend {n:g} {res}", -cost * scale)
    if "production" in beh:
        for res, amt in beh["production"].items():
            n = _resolve(amt, card_tags, ctx)
            phases = ctx.plant_phases if res == "plants" else ctx.phases
            v.prod[res] = v.prod.get(res, 0) + n
            v.add(f"{pre}{n:+g} {res} prod × {phases}", n * _unit(res, ctx) * phases * scale)
    if "stock" in beh:
        for res, amt in beh["stock"].items():
            n = _resolve(amt, card_tags, ctx)
            v.stock[res] = v.stock.get(res, 0) + n
            v.add(f"{pre}{n:g} {res}", n * _unit(res, ctx) * scale)
    if "standardResource" in beh:
        sr = beh["standardResource"]
        n = sr if isinstance(sr, (int, float)) else sr.get("count", 1)
        v.add(f"{pre}{n:g} standard resource", 2.0 * n * scale)
    if "drawCard" in beh:
        dc = beh["drawCard"]
        n = dc if isinstance(dc, (int, float)) else _resolve(dc.get("count", 1), card_tags, ctx)
        keep = n if isinstance(dc, (int, float)) else dc.get("keep", n)
        v.draws += keep * scale
        v.add(f"{pre}draw {keep:g}" + (f" of {n:g}" if keep != n else ""), (keep * CARD + (n - keep) * 0.5) * scale)
    if "tr" in beh:
        n = _resolve(beh["tr"], card_tags, ctx)
        v.tr += n * scale
        v.add(f"{pre}{n:g} TR", n * ctx.tr * scale)
    if "global" in beh:
        for param, steps in beh["global"].items():
            left = ctx.left.get(param, 0)
            gained = max(0, min(steps, left)) if steps > 0 else 0
            v.raises[param] += steps * scale
            v.tr += gained * scale
            v.add(f"{pre}{param} +{steps}" + (" (maxed)" if gained == 0 and steps > 0 else ""), gained * ctx.tr * scale)
    if "ocean" in beh:
        n = beh["ocean"].get("count", 1) if isinstance(beh["ocean"], dict) else 1
        gained = min(n, ctx.left["oceans"])
        v.raises["oceans"] += n * scale
        v.tiles["ocean"] += n * scale
        v.tr += gained * scale
        v.add(f"{pre}{n} ocean" + (" (oceans full)" if gained == 0 else ""), gained * (ctx.tr + OCEAN_ADJACENCY) * scale)
    if "greenery" in beh:
        o2 = 1 if ctx.left["oxygen"] else 0
        v.raises["oxygen"] += 1 * scale
        v.tiles["greenery"] += scale
        v.tr += o2 * scale
        v.add(f"{pre}greenery", (VP + o2 * ctx.tr) * scale)
    if "city" in beh:
        v.tiles["city"] += scale
        v.add(f"{pre}city tile (placement-dependent)", CITY_TILE * scale)
        if beh["city"].get("space"):
            v.flags.append("city goes on a reserved off-map area: it scores no greenery adjacency")
    if "tile" in beh:
        v.tiles["other"] += scale
        v.add(f"{pre}special tile", SPECIAL_TILE * scale)
    if "addResources" in beh:
        n = _resolve(beh["addResources"], card_tags, ctx)
        v.card_resources += n * scale
        v.add(f"{pre}{n:g} resource here", n * _resource_vp_value(card_name, ctx) * scale)
    if "addResourcesToAnyCard" in beh:
        adds = beh["addResourcesToAnyCard"]
        for add in adds if isinstance(adds, list) else [adds]:
            n = _resolve(add.get("count", 1), card_tags, ctx)
            each, target = _best_target(ctx, add.get("type"), exclude=card_name if add.get("excludeThis") else None,
                                        this_card=card_name)
            v.card_resources += n * scale
            v.add(f"{pre}{n:g} {add.get('type', 'resource')} to " + (target or "a card (no scoring target)"), n * each * scale)
    if "removeAnyPlants" in beh or "decreaseAnyProduction" in beh or "removeResourcesFromAnyCard" in beh:
        v.attack = True
    if "colonies" in beh:
        col = beh["colonies"]
        if "buildColony" in col:
            v.colonies += scale
            v.add(f"{pre}colony (placement bonus + owner bonuses)", COLONY * scale)
        if col.get("addTradeFleet"):
            v.add(f"{pre}+{col['addTradeFleet']} trade fleet", 6.0 * col["addTradeFleet"] * ctx.gens_left * scale)
    if "underworld" in beh:
        uw = beh["underworld"]
        if "excavate" in uw:
            ex = uw["excavate"]
            n = int(ex if isinstance(ex, (int, float)) else _resolve(ex.get("count", 1), card_tags, ctx))
            best = reachable_tokens(ctx)
            known = [t for t, _ in best[:n] if token_value(t, ctx) > blind_dig_value(ctx)]
            amount = sum(token_value(t, ctx) for t in known) + (n - len(known)) * blind_dig_value(ctx)
            v.tokens += n * scale
            label = f"{pre}excavate {n}" + (f" (best known: {', '.join(known)})" if known else f" (blind ≈{blind_dig_value(ctx):.1f} each)")
            v.add(label, amount * scale)
            if best:
                v.flags.append("identified tokens you can dig next to your tiles: " +
                               ", ".join(f"{t} at {sid} (≈{token_value(t, ctx):.0f})" for t, sid in best[:4]))
        if "identify" in uw:
            ident = uw["identify"]
            count = ident if isinstance(ident, (int, float)) else ident.get("count", 1)
            claim = 0 if isinstance(ident, (int, float)) else ident.get("claim", 0)
            if claim:
                v.tokens += claim * scale
                v.add(f"{pre}identify {count:g}, claim {claim:g} (best of {count:g} ≈{best_of_value(ctx, count):.1f})",
                      claim * best_of_value(ctx, count) * scale)
            else:
                v.add(f"{pre}identify {count:g}", 0.5 * scale)
        if "corruption" in uw:
            n = _resolve(uw["corruption"], card_tags, ctx)
            v.add(f"{pre}{n:g} corruption", n * corruption_value(ctx) * scale)
    if beh.get("titaniumValue"):
        v.manual.append("raises your titanium value: count your remaining space cards")
    if beh.get("steelValue"):
        v.manual.append("raises your steel value: count your remaining building cards")
    if beh.get("greeneryDiscount"):
        v.add(f"{pre}greeneries cost 1 plant less", ctx.plant * ctx.plant_phases * 0.5)


def value_card(name, ctx, cost=None, buying=False, model=None, nested=False):
    """Value a card for this player in this game. Returns a Valuation.

    `nested` is for valuations made inside another one (a hand card it unlocks): it skips unlock pricing,
    which would value cards again."""
    info = data.card(name) or {}
    beh = data.behavior(name) or ({"behavior": STANDARD_BEHAVIORS[name]} if name in STANDARD_BEHAVIORS else {})
    v = Valuation(name)
    v.info = info
    ctype = info.get("type")
    tags = info.get("tags", [])
    persistent = [] if ctype == "event" else tags
    v.persistent_tags = persistent
    v.event_tags = tags if ctype == "event" else []

    if ctype in ("corporation", "prelude") and info.get("startingMC"):
        v.add("starting M€" if ctype == "corporation" else "M€", info["startingMC"])
    if beh.get("behavior"):
        _apply(beh["behavior"], v, ctx, persistent, name)
    if beh.get("firstAction"):
        fa = dict(beh["firstAction"])
        fa.pop("text", None)
        _apply(fa, v, ctx, persistent, name, label="first action: ")

    vp = beh.get("vp")
    if isinstance(vp, (int, float)):
        v.add(f"{vp:g} VP", vp * VP)
    elif isinstance(vp, dict):
        if "resourcesHere" in vp:
            per = vp.get("per") or (vp["resourcesHere"] if isinstance(vp["resourcesHere"], int) else 1) or 1
            # Resources already here score now; future ones are valued where they come from (its action).
            current = (model or ctx.tableau.get(name) or {}).get("resources") or 0
            if current:
                v.add(f"{current} resources here ÷ {per} → VP", (current // per) * VP)
            if not (beh.get("action") or {}).get("addResources"):
                v.manual.append("VP depends on resources other cards or effects put here")
        elif "tag" in vp:
            n = _resolve({"tag": vp["tag"]}, persistent, ctx) // (vp.get("per") or 1)
            v.add(f"{n:g} VP from {vp['tag']} tags now", n * VP)
        elif "cities" in vp:
            n = (ctx.me["citiesCount"] + v.tiles["city"]) if vp.get("all") is False else \
                sum(p["citiesCount"] for p in ctx.players) + v.tiles["city"]
            per = vp.get("per", 1)
            v.add(f"{n // per:g} VP from {n} cities in play now", (n // per) * VP)
            v.flags.append("VP grows as anyone places cities")
        else:
            v.manual.append("VP rule not modelled: read the card")
    elif vp == "special":
        v.manual.append("special VP rule: read the card")

    action = beh.get("action")
    if action:
        trial = Valuation(name)
        _apply(action, trial, ctx, persistent, name)
        per_use = trial.value
        uses = ctx.gens_left
        if per_use > 0:
            v.add(f"action ×{uses} (≈{per_use:.1f} each)", per_use * uses)
            for k in v.raises:
                v.raises[k] += trial.raises[k] * uses
            v.tr += trial.tr * uses
            v.card_resources += trial.card_resources * uses
        else:
            v.flags.append(f"its action is worth ≈{per_use:.1f} M€ per use at current rates")
    if beh.get("tr") and not beh.get("behavior", {}).get("tr") and beh.get("bespokePlay"):
        tr = beh["tr"]
        steps = sum(min(tr.get(k, 0), ctx.left.get({"oceans": "oceans"}.get(k, k), 99)) for k in ("temperature", "oxygen", "venus", "oceans")) + tr.get("tr", 0)
        if steps:
            v.add(f"~{steps:g} TR (from the card's TR hint)", steps * ctx.tr)
            for k in ("temperature", "oxygen", "venus", "oceans"):
                v.raises[k] += tr.get(k, 0)
            v.tr += steps
    tr_count = TR_PER_TAG.get(name)
    if tr_count:
        # "Including this" counts the printed tags, even on an event.
        steps = _resolve(tr_count, tags, ctx)
        per = f" ÷ {tr_count['per']}" if tr_count.get("per") else ""
        v.add(f"{steps:g} TR from {tr_count['tag']} tags{per}, including this", steps * ctx.tr)
        v.tr += steps
    elif beh.get("bespokePlay"):
        v.manual.append("part of its play effect is custom code: read the card text")
    if beh.get("bespokeAction"):
        v.manual.append("its action is custom code: read the card text")
    if beh.get("triggers") and not (name in OWN_TRIGGERS and name not in ctx.tableau):  # else priced in _plan
        v.manual.append("ongoing effect (" + ", ".join(beh["triggers"]) + "): value depends on future plays")
    if name in ("Convert Plants", "Convert Heat"):
        v.flags.append("uses 8 " + ("plants" if name == "Convert Plants" else "heat") + " (priced at 0: no other use)")
    if not beh and ctype not in ("corporation",):
        v.manual.append("no structured effect data for this card")

    if cost is None:
        cost = (model or {}).get("calculatedCost", info.get("cost") or 0)
    if ctype in ("prelude", "corporation", "ceo"):
        cost = 0
    v.cost = cost or 0
    bought = ctype in ("automated", "active", "event")  # only project cards carry the 3 M€ purchase price
    v.paid = v.cost + (BUY_COST if buying and bought else 0)
    _context(v, ctx)
    _plan(v, ctx, nested)
    v.net = v.value - v.paid
    v.ratio = (v.value / v.paid) if v.paid else None
    return v


# --------------------------------------------------------------------------------------------- underworld

def corruption_value(ctx):
    """Corruption cancels negative card VP at game end (1 VP each); otherwise it mainly blocks attacks."""
    vp = ctx.me.get("victoryPointsBreakdown") or {}
    have = (ctx.me.get("underworldData") or {}).get("corruption", 0)
    return VP if abs(vp.get("negativeVP", 0) or 0) > have else 1.0


def token_value(token, ctx):
    """M€ value of claiming one underground token now."""
    microbe, _ = _best_target(ctx, "Microbe")
    return {
        "nothing": 0, "card1": CARD, "card2": 2 * CARD,
        "corruption1": corruption_value(ctx), "corruption2": 2 * corruption_value(ctx),
        "steel2plant": 2 * ctx.steel + ctx.plant, "steel1production": ctx.steel * ctx.phases,
        "titanium2": 2 * ctx.titanium, "titanium1production": ctx.titanium * ctx.phases,
        "titaniumandplant": ctx.titanium + ctx.plant, "plant2": 2 * ctx.plant, "plant3": 3 * ctx.plant,
        "plant1production": ctx.plant * ctx.plant_phases, "energy2": 2 * ctx.energy,
        "energy1production": ctx.energy * ctx.phases, "heat2production": 2 * ctx.heat * ctx.phases,
        "microbe2": 2 * microbe, "tr": ctx.tr,
        "ocean": (ctx.tr + OCEAN_ADJACENCY - 4) if ctx.left["oceans"] else 0,
        "sciencetag": 2.0, "planttag": 2.0, "anyresource1": 2.0, "place6mc": 0,
        # Temporary bonuses pay per 2 °C raised this generation; assume one step.
        "plant2pertemp": 2 * ctx.plant if ctx.left["temperature"] else 0,
        "steel2pertemp": 2 * ctx.steel if ctx.left["temperature"] else 0,
        "titanium1pertemp": ctx.titanium if ctx.left["temperature"] else 0,
        "microbe2pertemp": 2 * microbe if ctx.left["temperature"] else 0,
        "mcprod1pertemp": ctx.phases if ctx.left["temperature"] else 0,
        "oceanrequirementmod": 1.0, "oxygenrequirementmod": 1.0, "temprequirementmod": 1.0,
    }.get(token, 1.0)


def _bag(ctx):
    """Tokens still in the bag: the full set minus identified and claimed ones visible to us."""
    bag = dict(TOKEN_COUNTS)
    seen = [s["undergroundResource"] for s in ctx.game.get("spaces", []) if s.get("undergroundResource")]
    for p in ctx.players:
        seen += [t["token"] for t in (p.get("underworldData") or {}).get("tokens", [])]
    for t in seen:
        if bag.get(t, 0) > 0:
            bag[t] -= 1
    return bag


def blind_dig_value(ctx):
    bag = _bag(ctx)
    total = sum(bag.values())
    return sum(n * token_value(t, ctx) for t, n in bag.items()) / total if total else 0.0


def best_of_value(ctx, k):
    """Expected value of the best of k random tokens (drawn with replacement; close enough)."""
    bag = _bag(ctx)
    total = sum(bag.values())
    if not total:
        return 0.0
    values = sorted(token_value(t, ctx) for t, n in bag.items() for _ in range(n))
    n = len(values)
    # P(max <= values[i]) = ((i+1)/n)^k
    expected, prev = 0.0, 0.0
    for i, val in enumerate(values):
        cdf = ((i + 1) / n) ** k
        expected += val * (cdf - prev)
        prev = cdf
    return expected


def reachable_tokens(ctx):
    """Identified, unexcavated tokens on spaces you may excavate (next to your tiles or excavations)."""
    spaces = {s["id"]: s for s in ctx.game.get("spaces", [])}
    board = ctx.game["gameOptions"].get("boardName", "")
    mine = [s["id"] for s in spaces.values()
            if (s.get("color") == ctx.me["color"] and s.get("tileType") is not None) or s.get("excavator") == ctx.me["color"]]
    near = {a for sid in mine for a in data.adjacency(board, sid)} if mine else set(spaces)
    hits = [(s["undergroundResource"], sid) for sid, s in spaces.items()
            if sid in near and s.get("undergroundResource") and not s.get("excavator")]
    return sorted(hits, key=lambda h: -token_value(h[0], ctx))


# --------------------------------------------------------------------------------------------- context

def _context(v, ctx):
    _requirements(v, ctx)
    _simulate(v, ctx)
    _milestones(v, ctx)
    _awards(v, ctx)
    _rival_triggers(v, ctx)
    if v.attack:
        _attack(v, ctx)
    if v.event_tags:
        v.flags.append("event: its tags count for planetary tracks and triggers now, but not for milestones or awards")


_REQ = re.compile(r"^(max )?(\d+) (\w+) tag")


def requirement_status(req, ctx, extra_tags=()):
    """(met, text) for one requirement string from cards.json, or (None, text) if not checkable."""
    m = _REQ.match(req)
    if m:
        n, tag = int(m.group(2)), m.group(3)
        have = ctx.tags.get(tag, 0) + ctx.tags.get("wild", 0) + list(extra_tags).count(tag)
        return (have <= n if m.group(1) else have >= n), f"{tag} tags {have}/{n}"
    m = re.match(r"^(max )?(temperature|oxygen|oceans|venus|tr|cities|colonies|greeneries) (-?\d+)", req)
    if m:
        n = int(m.group(3))
        have = {"temperature": ctx.temp, "oxygen": ctx.oxygen, "oceans": ctx.oceans, "venus": ctx.venus,
                "tr": ctx.me["terraformRating"], "cities": ctx.me["citiesCount"],
                "colonies": ctx.me["coloniesCount"], "greeneries": None}[m.group(2)]
        if have is None:
            return None, req
        return (have <= n if m.group(1) else have >= n), f"{m.group(2)} {have} (needs {'≤' if m.group(1) else '≥'}{n})"
    return None, req


def _requirements(v, ctx):
    for req in v.info.get("req", []):
        met, text = requirement_status(req, ctx)
        if met is False:
            v.flags.append(f"NOT PLAYABLE YET: {text}")
        elif met is None and "any player" not in req:
            v.manual.append(f"check requirement: {req}")


def _reward_value(reward, ctx):
    return {
        "1vp": VP, "2vp": 2 * VP, "3mc": 3.0, "6mc": 6.0, "any_resource": 2.0, "card": CARD, "city": CITY_TILE,
        "delegate": 1.0 if ctx.expansions.get("turmoil") else 0.0, "energy": ctx.energy, "energy_production": ctx.energy * ctx.phases, "floater": 1.0,
        "greenery": VP + (ctx.tr if ctx.left["oxygen"] else 0), "heat": ctx.heat, "heat_production": ctx.heat * ctx.phases,
        "ocean": (ctx.tr + OCEAN_ADJACENCY) if ctx.left["oceans"] else 0, "plant": ctx.plant,
        "plant_production": ctx.plant * ctx.plant_phases, "resource": 1.0, "steel": ctx.steel,
        "steel_production": ctx.steel * ctx.phases, "titanium": ctx.titanium,
        "titanium_production": ctx.titanium * ctx.phases, "tr": ctx.tr, "venus_scale": ctx.tr if ctx.left["venus"] else 0,
        "moon_road": SPECIAL_TILE, "moon_mine": SPECIAL_TILE,
    }.get(reward, 1.0)


def _simulate(v, ctx):
    """Run the card's effects through one event queue against a simulated game state.

    The card's own steps, tiles and tags are queued first (their TR is priced in _apply). Each handler
    updates the state and may queue further events: oxygen 8% queues a temperature step, 0 °C queues an
    ocean, a planetary-track reward can raise Venus or place an ocean, greenery or city. Bonus events are priced
    here, labelled with what set them off. When the queue is empty, your own cards' triggers are priced
    from everything that happened (see OWN_TRIGGERS)."""
    sim = _Sim(v, ctx)
    sim.run()
    sim.finish()


class _Sim:
    def __init__(self, v, ctx):
        self.v, self.ctx = v, ctx
        self.temp, self.oxygen, self.venus = ctx.temp, ctx.oxygen, ctx.venus
        self.left = dict(ctx.left)
        self.tracks = dict(ctx.game.get("pathfinders") or {})
        self.queue = deque()
        self.last = []
        # What actually happened, own effects and bonuses together, for triggers and rival checks.
        self.steps = {"temperature": 0, "oxygen": 0, "venus": 0}
        self.tiles = {"ocean": 0, "greenery": v.tiles["greenery"], "city": v.tiles["city"]}
        self.bonus_tr = 0.0

    @staticmethod
    def _whole(x):
        return max(0, int(x + 1e-9))

    def run(self):
        r, v = self.v.raises, self.v
        # The card's own effects go first, oceans before temperature (so its ocean fills the track before
        # a 0 °C bonus ocean is counted) and temperature before oxygen (so an oxygen bonus step only gets
        # the temperature room the card leaves).
        self.queue.append(("ocean", self._whole(r["oceans"]), None, ""))
        self.queue.append(("temperature", self._whole(r["temperature"]), None, ""))
        self.queue.append(("oxygen", self._whole(r["oxygen"]), None, ""))
        self.queue.append(("venus", self._whole(r["venus"]), None, ""))
        for track in PLANETARY:
            n = (v.persistent_tags + v.event_tags).count(track)
            if n:
                self.queue.append(("track", (track, n), None, ""))
        guard = 0
        while self.queue and guard < 200:
            kind, n, label, via = self.queue.popleft()
            getattr(self, "_" + kind)(n, label, via)
            guard += 1

    def _price(self, label, amount, tr=0):
        """Price a bonus event; label is None for the card's own effects, which _apply already priced."""
        if label:
            self.v.add(label, amount)
            self.bonus_tr += tr
            self.v.tr += tr

    def _temperature(self, n, label, via):
        ctx, v = self.ctx, self.v
        for _ in range(min(n, self.left["temperature"])):
            before, self.temp = self.temp, self.temp + 2
            self.left["temperature"] -= 1
            self.steps["temperature"] += 1
            self._price(label, ctx.tr, tr=1)
            label = label and f"bonus temperature step{via}"
            for t in (-24, -20):
                if before < t <= self.temp:
                    v.add(f"temperature reaches {t}°C: +1 heat production{via}", ctx.heat * ctx.phases)
            if before < 0 <= self.temp:
                if self.left["oceans"]:
                    self.queue.append(("ocean", 1, f"temperature reaches 0°C: bonus ocean{via}", via))
                else:
                    v.flags.append(f"temperature reaches 0°C{via} but oceans are full: no bonus ocean")
            if not self.left["temperature"]:
                self.last.append("temperature")

    def _oxygen(self, n, label, via):
        ctx, v = self.ctx, self.v
        for _ in range(min(n, self.left["oxygen"])):
            before, self.oxygen = self.oxygen, self.oxygen + 1
            self.left["oxygen"] -= 1
            self.steps["oxygen"] += 1
            self._price(label, ctx.tr, tr=1)
            label = label and f"bonus oxygen step{via}"
            if before < 8 <= self.oxygen:
                if self.left["temperature"]:
                    self.queue.append(("temperature", 1, "oxygen reaches 8%: bonus temperature step", " (via oxygen 8%)"))
                else:
                    v.flags.append("oxygen reaches 8% but temperature is maxed: no bonus")
            if not self.left["oxygen"]:
                self.last.append("oxygen")

    def _ocean(self, n, label, via):
        placed = min(n, self.left["oceans"])
        self.left["oceans"] -= placed
        self.tiles["ocean"] += placed
        if placed:
            self._price(label, placed * (self.ctx.tr + OCEAN_ADJACENCY), tr=placed)
            if not self.left["oceans"]:
                self.last.append("oceans")

    def _greenery(self, n, label, via):
        # Only bonus greeneries come through here; the card's own are already in v.raises["oxygen"].
        self.tiles["greenery"] += n
        self._price(label, n * VP)
        self.queue.append(("oxygen", n, f"oxygen step from that greenery{via}", via))

    def _city(self, n, label, via):
        self.tiles["city"] += n
        self._price(label, n * CITY_TILE)

    def _venus(self, n, label, via):
        ctx, v = self.ctx, self.v
        for _ in range(min(n, self.left["venus"])):
            before, self.venus = self.venus, self.venus + 2
            self.left["venus"] -= 1
            self.steps["venus"] += 1
            self._price(label, ctx.tr, tr=1)
            label = label and f"bonus Venus step{via}"
            if ctx.alt_venus:
                if self.venus > 16:
                    v.add(f"alternative Venus board: resource reward{via}", 2.0)
            else:
                if before < 8 <= self.venus:
                    v.add(f"Venus reaches 8%: draw a card{via}", CARD)
                if before < 16 <= self.venus:
                    v.add(f"Venus reaches 16%: +1 TR{via}", ctx.tr)
                    self.bonus_tr += 1
                    v.tr += 1
            if not self.left["venus"]:
                self.last.append("venus")

    # Planetary-track rewards that change the board go back into the queue instead of a flat price.
    _CHAIN_REWARDS = {"venus_scale": "venus", "ocean": "ocean", "greenery": "greenery", "city": "city"}

    def _track(self, payload, label, via):
        track, n = payload
        ctx, v = self.ctx, self.v
        pos = self.tracks.get(track)
        if pos is None or pos < 0:
            return
        layout = data.planetary_tracks().get(track, [])
        for step in range(pos + 1, min(pos + n, len(layout) - 1) + 1):
            space = layout[step]
            mine, everyone = space.get("risingPlayer", []), space.get("everyone", [])
            if mine:
                flat = [r for r in mine if r not in self._CHAIN_REWARDS]
                label = f"{track} track {step}: you get {', '.join(mine)}"
                v.add(label, sum(_reward_value(r, ctx) for r in flat))
                for r in mine:
                    if r in self._CHAIN_REWARDS:
                        cause = f" (via {track} track {step})"
                        self.queue.append((self._CHAIN_REWARDS[r], 1, f"{track} track {step}: you get {r}", cause))
                if "tr" in flat:
                    self.bonus_tr += flat.count("tr")
                    v.tr += flat.count("tr")
            if everyone:
                each = sum(_reward_value(r, ctx) for r in everyone)
                v.add(f"{track} track {step}: everyone gets {', '.join(everyone)}", each)
                v.flags.append(f"{track} track {step} also gives each rival {', '.join(everyone)} (≈{each:.0f} M€ each)")
            if space.get("mostTags"):
                v.flags.append(f"{track} track reaches its end: most {track} tags scores {', '.join(space['mostTags'])}")
        self.tracks[track] = pos + n

    def finish(self):
        ctx, v = self.ctx, self.v
        v.sim = {**self.steps, **self.tiles}
        # Milestone and award checks run after the simulation and must include bonus tiles.
        # These counts already include the card's own tiles, so replace rather than add.
        v.tiles.update(self.tiles)
        if "temperature" in self.last:
            holders = [f"{p['name']} ({p['heat']} heat)" for p in ctx.rivals if p["heat"] >= 8]
            v.flags.append("takes the LAST temperature step" + (f": strands {', '.join(holders)}" if holders else ""))
        if "oxygen" in self.last:
            holders = [f"{p['name']} ({p['plants']} plants)" for p in ctx.rivals if p["plants"] >= 8]
            v.flags.append("takes the LAST oxygen step" + (f": later greeneries give no TR ({', '.join(holders)} holding plants)" if holders else ""))
        if "venus" in self.last:
            v.flags.append("takes the LAST Venus step")
        if "oceans" in self.last:
            v.flags.append("places the LAST ocean: ends every ocean action and ocean card for the table")
        if ctx.remaining_steps and not self.left["temperature"] and not self.left["oxygen"] and not self.left["oceans"] and \
                (not ctx.venus_counts or not self.left["venus"]):
            v.flags.append("COMPLETES TERRAFORMING: the game ends after this generation")
        # Exploitation Of Venus pays whoever raises Venus, whoever owns it.
        if self.steps["venus"]:
            for p in ctx.players:
                if any(c["name"] == "Exploitation Of Venus" for c in p.get("tableau", [])):
                    who = "your" if p["color"] == ctx.me["color"] else f"{p['name']}'s"
                    v.add(f"{who} Exploitation Of Venus pays you per Venus step", 2.0 * self.steps["venus"])
        _own_triggers(v, ctx, self)


# Your own cards that pay you when this card's effects happen. The app implements these payouts in
# custom code, so behaviors.json only names the hook; the amounts here come from the card text.
# event → what one occurrence pays: ("mc", n), a stock resource, "prod:<resource>", "card",
# "here" (a resource on the trigger card itself) or "res:<Type>" (a resource on your best card of that type).
OWN_TRIGGERS = {
    "Homeostasis Bureau": [("temperature", [("mc", 3)], "+3 M€ per temperature step")],
    "Venus Contract": [("venus", [("mc", 3)], "+3 M€ per Venus step")],
    "Aphrodite": [("venus", [("mc", 2)], "+2 M€ per Venus step")],
    "Terraforming Deal": [("tr", [("mc", 2)], "+2 M€ per TR")],
    "United Nations Mission One": [("tr", [("mc", 1)], "+1 M€ per TR")],
    "Arctic Algae": [("ocean", [("plants", 2)], "+2 plants per ocean")],
    "Lakefront Resorts": [("ocean", [("prod:megacredits", 1)], "+1 M€ production per ocean")],
    "Polaris": [("ocean", [("prod:megacredits", 1), ("mc", 4)], "+1 M€ production and 4 M€ per ocean")],
    "PolderTECH Dutch": [("ocean", [("energy", 1)], "+1 energy per ocean"), ("greenery", [("plants", 1)], "+1 plant per greenery")],
    "Herbivores": [("greenery", [("here", 1)], "+1 animal per greenery")],
    "Gordon": [("greenery", [("mc", 2)], "+2 M€ per greenery"), ("city", [("mc", 2)], "+2 M€ per city")],
    "Rover Construction": [("city", [("mc", 2)], "+2 M€ per city")],
    "Tharsis Republic": [("city", [("prod:megacredits", 1), ("mc", 3)], "+1 M€ production and 3 M€ per city")],
    "Immigrant City": [("city", [("prod:megacredits", 1)], "+1 M€ production per city")],
    "Pets": [("city", [("here", 1)], "+1 animal per city")],
    "Steelaris": [("city", [("steel", 1), ("plants", 1)], "+1 steel and 1 plant per city")],
    "Interplanetary Cinematics": [("event", [("mc", 2)], "+2 M€ per event")],
    "Media Group": [("event", [("mc", 3)], "+3 M€ per event")],
    "Martian Insurance Group": [("event", [("prod:megacredits", 1)], "+1 M€ production per event")],
    "Optimal Aerobraking": [("space_event", [("mc", 3), ("heat", 3)], "+3 M€ and 3 heat per space event")],
    "Palladin Shipping": [("space_event", [("titanium", 1)], "+1 titanium per space event")],
    "Point Luna": [("tag:earth", [("card", 1)], "draws a card per Earth tag")],
    "Space Relay": [("card:jovian", [("card", 1)], "draws a card per Jovian card")],
    "Ambient": [("card:venus", [("prod:heat", 1)], "+1 heat production per Venus card")],
    "Robin Haulings": [("card:venus", [("res:Floater", 1)], "+1 floater per Venus card")],
    "Microbiology Patents": [("card:microbe", [("prod:megacredits", 1)], "+1 M€ production per microbe card")],
    "Advertising": [("cost20", [("prod:megacredits", 1)], "+1 M€ production for a 20+ M€ card")],
    "CrediCor": [("cost20", [("mc", 4)], "+4 M€ for a 20+ M€ card or standard project")],
    "Spin-off Department": [("cost20", [("card", 1)], "draws a card for a 20+ M€ card")],
    "Sagitta Frontier Services": [("notags", [("mc", 4)], "+4 M€ for a card with no tags"),
                                  ("onetag", [("mc", 1)], "+1 M€ for a card with one tag")],
    "Standard Technology": [("standard_project", [("mc", 3)], "+3 M€ per standard project")],
    "Venusian Animals": [("tag:science", [("here", 1)], "+1 animal per science tag")],
    "Terraforming Robots": [("tag:mars", [("here", 1)], "+1 robot per Mars tag")],
    "Martian Repository": [("tag:science", [("here", 1)], "+1 data per science tag"), ("tag:mars", [("here", 1)], "+1 data per Mars tag")],
    "Martian Zoo": [("tag:earth", [("here", 1)], "+1 animal per Earth tag")],
    "Decomposers": [("tag:bio", [("here", 1)], "+1 microbe per plant, animal or microbe tag")],
    "Arklight": [("tag:plant", [("here", 1)], "+1 animal per plant tag"), ("tag:animal", [("here", 1)], "+1 animal per animal tag")],
    "Ecological Zone": [("tag:plant", [("here", 1)], "+1 animal per plant tag"), ("tag:animal", [("here", 1)], "+1 animal per animal tag")],
    "Viral Enhancers": [("tag:bio", [("plants", 1)], "+1 plant per plant, animal or microbe tag")],
    "EcoTec": [("tag:bio", [("plants", 1)], "+1 plant per plant, animal or microbe tag")],
    "GMO Contract": [("tag:bio", [("mc", 2)], "+2 M€ per plant, animal or microbe tag")],
    "Soil Bacteria": [("tag:plant", [("plants", 1)], "+1 plant per plant tag"), ("tag:microbe", [("plants", 1)], "+1 plant per microbe tag")],
    "Albedo Plants": [("tag:plant", [("heat", 3)], "+3 heat per plant tag")],
}
OWN_TRIGGERS["Ecological Zone:ares"] = OWN_TRIGGERS["Ecological Zone"]

_NO_CARD_TRIGGERS = ("Convert Plants", "Convert Heat")


def _trigger_counts(v, ctx, sim):
    """How many times each OWN_TRIGGERS event happens when this card or project is used."""
    info = v.info or {}
    tags = v.persistent_tags + v.event_tags
    project = info.get("type") in ("automated", "active", "event")
    standard = v.name in STANDARD_BEHAVIORS and v.name not in _NO_CARD_TRIGGERS
    base = info.get("cost") if project else (v.cost if standard else 0)
    counts = {
        "temperature": sim.steps["temperature"], "oxygen": sim.steps["oxygen"], "venus": sim.steps["venus"],
        "ocean": sim.tiles["ocean"], "greenery": sim.tiles["greenery"], "city": sim.tiles["city"],
        "tr": max(0.0, v.tr), "standard_project": 1 if standard else 0,
        "cost20": 1 if (project or standard) and (base or 0) >= 20 else 0,
    }
    if project:
        counts.update({
            "event": 1 if info.get("type") == "event" else 0,
            "space_event": 1 if info.get("type") == "event" and "space" in tags else 0,
            "notags": 1 if not tags else 0, "onetag": 1 if len(tags) == 1 else 0,
            "tag:bio": sum(tags.count(t) for t in ("plant", "animal", "microbe")),
        })
        for t in set(tags):
            counts[f"tag:{t}"] = tags.count(t)
            counts[f"card:{t}"] = 1
    return counts


def _payout(kind, n, owner, ctx):
    if kind == "mc":
        return n
    if kind in ("plants", "heat", "steel", "titanium", "energy"):
        return n * _unit(kind, ctx)
    if kind.startswith("prod:"):
        res = kind[5:]
        return n * _unit(res, ctx) * (ctx.plant_phases if res == "plants" else ctx.phases)
    if kind == "card":
        return n * CARD
    if kind == "here":
        return n * _resource_vp_value(owner, ctx)
    if kind.startswith("res:"):
        return n * _best_target(ctx, kind[4:])[0]
    return 0.0


def _own_triggers(v, ctx, sim):
    counts = _trigger_counts(v, ctx, sim)
    v.trigger_counts = counts
    for owner in ctx.tableau:
        if owner == v.name:
            continue
        for event, pays, text in OWN_TRIGGERS.get(owner, []):
            n = counts.get(event, 0)
            if n:
                v.add(f"your {owner}: {text} (×{n:g})", sum(_payout(k, amt * n, owner, ctx) for k, amt in pays))


_MILESTONE_METRICS = {
    "Terraformer": "tr", "Terraformer29": "tr", "Mayor": "cities", "Gardener": "greeneries", "Builder": "tag:building",
    "Builder7": "tag:building", "Ecologist": "tags:plant,microbe,animal", "Tycoon": "projects", "Tycoon10": "blue_green",
    "Legend": "events", "Legend4": "events", "Diversifier": "distinct", "Tactician": "reqcards", "Tactician4": "reqcards",
    "Energizer": "prod:energy", "Rim Settler": "tag:jovian", "Terran": "tag:earth", "Terran5": "tag:earth",
    "Economizer": "prod:heat", "Martian": "tag:mars", "T. Spacefarer": "tag:space", "V. Spacefarer": "tag:space",
    "Spacefarer4": "tag:space", "Architect": "tag:city", "C. Forester": "prod:plants", "Forester": "prod:plants",
    "V. Electrician": "tag:power", "Smith": "prod:steel,titanium", "Metallurgist": "prod:steel,titanium",
    "Pioneer": "colonies", "Agronomist": "tag:plant", "Engineer": "prod:energy,heat", "Researcher": "tag:science",
    "Fundraiser": "prod:megacredits", "Sponsor": "cost20", "One Giant Step": "tag:moon", "Hoverlord": "res:Floater",
    "Farmer": "res:Animal,Microbe", "Planner": "hand", "Producer": "prod:all", "Tunneler": "tokens",
}

_AWARD_METRICS = {
    "Landlord": "tiles", "Scientist": "tag:science", "Banker": "prod:megacredits", "Celebrity": "cost20",
    "Benefactor": "tr", "Contractor": "tag:building", "Cultivator": "greeneries", "Magnate": "automated",
    "Space Baron": "tag:space", "Venuphile": "tag:venus", "Full Moon": "tag:moon", "Botanist": "prod:plants",
    "Promoter": "events", "A. Manufacturer": "active", "Biologist": "tags:plant,microbe,animal", "Forecaster": "reqcards",
    "Naturalist": "prod:plants,heat", "Voyager": "tag:jovian", "Traveller": "tags:jovian,earth",
    "Manufacturer": "prod:steel,heat", "Blacksmith": "prod:steel,titanium", "Kingpin": "crime", "Administrator": "notags",
    "Constructor": "colonies+cities", "Electrician": "tag:power", "Incorporator": "cost10", "Innovator": "projects_events",
    "Investor": "tag:earth", "Metropolist": "cities", "Mogul": "prod:nonmc", "Physicist": "tags:science,space",
    "Visionary": "hand", "Miner": "stock:steel,titanium", "Thermalist": "stock:heat", "Industrialist": "stock:steel,energy",
    "Excentric": "card_resources", "Zoologist": "res:Animal", "A. Zoologist": "res:Animal,Microbe",
    "Excavator": "tokens",
}


def _metric_delta(metric, v, ctx):
    """How much playing this card moves one milestone/award metric for you (None = not modelled)."""
    info = v.info
    ctype = info.get("type")
    project = ctype in ("automated", "active", "event")
    if metric.startswith("tag:"):
        return v.persistent_tags.count(metric[4:])
    if metric.startswith("tags:"):
        return sum(v.persistent_tags.count(t) for t in metric[5:].split(","))
    if metric.startswith("prod:"):
        keys = metric[5:]
        if keys == "all":
            return sum(v.prod.values())
        if keys == "nonmc":
            return sum(n for r, n in v.prod.items() if r != "megacredits")
        return sum(v.prod.get(r, 0) for r in keys.split(","))
    if metric.startswith("stock:"):
        return sum(v.stock.get(r, 0) for r in metric[6:].split(","))
    if metric.startswith("res:"):
        rtype = metric[4:].split(",")
        return v.card_resources if (info.get("resource") in rtype) else None
    return {
        "tr": v.tr, "cities": v.tiles["city"], "greeneries": v.tiles["greenery"],
        "tiles": v.tiles["city"] + v.tiles["greenery"] + v.tiles["other"],
        "projects": 1 if ctype in ("automated", "active") else 0,
        "blue_green": 1 if ctype in ("automated", "active") else 0,
        "projects_events": 1 if project else 0,
        "events": 1 if ctype == "event" else 0,
        "automated": 1 if ctype == "automated" else 0,
        "active": 1 if ctype == "active" else 0,
        "reqcards": 1 if info.get("req") and ctype in ("automated", "active") else 0,
        "cost20": 1 if (info.get("cost") or 0) >= 20 and ctype in ("automated", "active") else 0,
        "cost10": 1 if (info.get("cost") or 99) <= 10 and ctype in ("automated", "active") else 0,
        "colonies": v.colonies, "colonies+cities": v.colonies + v.tiles["city"],
        "crime": (v.persistent_tags + v.event_tags).count("crime"),
        "notags": 1 if not info.get("tags") and ctype in ("automated", "active") else 0,
        "distinct": len({t for t in v.persistent_tags if t not in ("event", "wild", "clone")}
                        - {t for t, n in ctx.tags.items() if n and t not in ("event",)}),
        "hand": v.draws - 1, "card_resources": v.card_resources, "tokens": v.tokens,
    }.get(metric)


def _milestones(v, ctx):
    ms = ctx.game.get("milestones") or []
    claimed = sum(1 for m in ms if m.get("playerName"))
    if claimed >= 3:
        return
    for m in ms:
        if m.get("playerName"):
            continue
        metric = _MILESTONE_METRICS.get(m["name"])
        if not metric:
            continue
        delta = _metric_delta(metric, v, ctx)
        if not delta:
            continue
        scores = {s["color"]: s for s in m.get("scores", [])}
        mine = scores.get(ctx.me["color"], {}).get("score")
        target = re.search(r"(\d+)", data.milestone_text(m["name"]) or "")
        if mine is None or not target:
            continue
        need = int(target.group(1))
        if mine < need <= mine + delta:
            v.add(f"lets you claim {m['name']} (5 VP for 8 M€)", 5 * VP - 8)
            v.flags.append(f"MILESTONE: {m['name']} {mine}→{mine + delta}/{need}: claimable after this")
        elif mine < need and mine + delta >= need - 2:
            v.flags.append(f"milestone {m['name']}: {mine}→{mine + delta} of {need}")


def _award_points(scores, n_players):
    """VP each color gets from an award, using first 5 / second 2 and the tie rules."""
    if not scores:
        return {}
    top = max(scores.values())
    firsts = [c for c, s in scores.items() if s == top]
    out = {c: 0 for c in scores}
    for c in firsts:
        out[c] = 5
    if len(firsts) == 1 and n_players > 2:
        rest = [s for c, s in scores.items() if c not in firsts]
        if rest:
            second = max(rest)
            for c, s in scores.items():
                if s == second and c not in firsts:
                    out[c] = 2
    return out


def _awards(v, ctx):
    aw = ctx.game.get("awards") or []
    funded = sum(1 for a in aw if a.get("playerName"))
    for a in aw:
        if funded >= 3 and not a.get("playerName"):
            continue
        metric = _AWARD_METRICS.get(a["name"])
        if not metric:
            continue
        delta = _metric_delta(metric, v, ctx)
        if not delta:
            continue
        scores = {s["color"]: s["score"] for s in a.get("scores", [])}
        if ctx.me["color"] not in scores:
            continue
        before = _award_points(scores, len(ctx.players))
        after_scores = dict(scores)
        after_scores[ctx.me["color"]] += delta
        after = _award_points(after_scores, len(ctx.players))
        mine = after[ctx.me["color"]] - before[ctx.me["color"]]
        rival_changes = [f"{ctx.names[c]} {after[c] - before[c]:+d}" for c in scores
                         if c != ctx.me["color"] and after[c] != before[c]]
        status = "funded" if a.get("playerName") else "not funded"
        text = f"{a['name']} ({status}): you {scores[ctx.me['color']]}→{after_scores[ctx.me['color']]}"
        if mine or rival_changes:
            text += f": you {mine:+d} VP" + (f", {', '.join(rival_changes)} VP" if rival_changes else "")
            if a.get("playerName") and mine:
                v.add(f"{a['name']} award position", mine * VP)
            v.flags.append("AWARD " + text)



# --------------------------------------------------------------------------------------------- planned tableau
# The hand counts as future plays. Each project card in hand gets a chance of being played before the game
# ends (affordable with the hand's share of your money; requirement met in time at the table's pace), and
# effects that depend on future plays are priced from those chances. Every number below is an assumption
# taken from the rules or plain reasoning, not fitted to game results.

PROJECT = ("automated", "active", "event")
# Share of the money you will still have that goes to cards already in hand. The rest buys new cards
# (3 M€ each), standard projects, milestones and awards.
HAND_BUDGET_SHARE = 0.5
# Generations a hand card typically waits for money and an action before it is played.
HAND_PLAY_DELAY = 1.0
# Chance that a requirement met only by other hand cards' tags is met in time (they must be played first).
HAND_TAG_REQ_P = 0.6
# Chance for a requirement this model cannot check (greeneries, any player's cities, colonies...).
UNCHECKED_REQ_P = 0.7
# A hand effect card only fires on this card if it is played first: assume it is, half of the time.
ORDER_SHARE = 0.5
# Venus steps per generation when Venus does not count towards the game end (nobody needs to finish it).
UNCOUNTED_VENUS_RATE = 1.0
_PARAM_UNIT = {"temperature": 2, "oxygen": 1, "oceans": 1, "venus": 2}
_SELF_TRIGGER = re.compile(r"including th(is|ese)", re.I)


def future_matches(ctx, event):
    """Expected number of times `event` happens from cards not drawn yet, over the rest of the game.

    Events use the _play_counts keys ("tag:earth", "card:jovian", "card" for any project card, "event",
    "space_event", "cost20", "notags", "onetag", "tag:bio") and the OWN_TRIGGERS ones ("ocean", "city", ...).
    Drawn cards are counted from the deck's composition (tfm/deck.py); tile and parameter events are 0."""
    return deck.future_matches(ctx, event)


def _kept_tags(name):
    """Tags that stay on the tableau when the card is played (an event's tags do not)."""
    info = data.card(name) or {}
    return [] if info.get("type") == "event" else list(info.get("tags", []))


def _play_counts(name):
    """How often each trigger/discount event happens when this project card is played, from the card data
    alone (bonus events from thresholds are left out)."""
    info = data.card(name) or {}
    ctype = info.get("type")
    if ctype not in PROJECT:
        return {}
    tags = info.get("tags", [])
    counts = {
        "card": 1, "event": 1 if ctype == "event" else 0,
        "space_event": 1 if ctype == "event" and "space" in tags else 0,
        "notags": 1 if not tags else 0, "onetag": 1 if len(tags) == 1 else 0,
        "cost20": 1 if (info.get("cost") or 0) >= 20 else 0,
        "tag:bio": sum(tags.count(t) for t in ("plant", "animal", "microbe")),
    }
    for t in set(tags):
        counts[f"tag:{t}"] = tags.count(t)
        counts[f"card:{t}"] = 1
    beh = (data.behavior(name) or {}).get("behavior") or {}
    steps = dict(beh.get("global") or {})
    oceans = (beh["ocean"].get("count", 1) if isinstance(beh["ocean"], dict) else 1) if "ocean" in beh else 0
    counts.update({"ocean": oceans, "city": 1 if "city" in beh else 0, "greenery": 1 if "greenery" in beh else 0,
                   "temperature": steps.get("temperature", 0), "oxygen": steps.get("oxygen", 0) + ("greenery" in beh),
                   "venus": steps.get("venus", 0)})
    tr = beh.get("tr") if isinstance(beh.get("tr"), (int, float)) else 0
    counts["tr"] = tr + oceans + counts["temperature"] + counts["oxygen"] + counts["venus"]
    return {k: n for k, n in counts.items() if n}


def _param_rate(param, ctx):
    """Steps per generation of one parameter: the table's pace, split by the steps each parameter has left."""
    if param == "venus" and not ctx.venus_counts:
        return UNCOUNTED_VENUS_RATE if ctx.left["venus"] else 0.0
    return ctx.pace * ctx.left[param] / ctx.remaining_steps if ctx.remaining_steps else 0.0


def _within(wait, ctx):
    """Chance a play `wait` generations from now still happens: 1 before the last generation, fading over it."""
    return max(0.0, min(1.0, ctx.gens_left - wait))


def _req_timing(req, ctx, extra_tags=(), hand_tags=(), raises=None):
    """(chance, generations to wait) for one requirement string from cards.json."""
    raises = raises or {}
    m = _REQ.match(req)
    if m:
        n, tag = int(m.group(2)), m.group(3)
        have = ctx.tags.get(tag, 0) + ctx.tags.get("wild", 0) + list(extra_tags).count(tag)
        if m.group(1):
            return (1.0, 0.0) if have <= n else (0.0, math.inf)
        if have >= n:
            return 1.0, 0.0
        hand = list(hand_tags).count(tag)
        if have + hand >= n:
            return HAND_TAG_REQ_P, HAND_PLAY_DELAY
        future = future_matches(ctx, f"tag:{tag}")
        if future <= 0:
            return 0.0, math.inf
        wait = (n - have - hand) / (future / ctx.gens_left)
        return _within(wait, ctx), wait
    m = re.match(r"^(max )?(temperature|oxygen|oceans|venus) (-?\d+)", req)
    if m:
        param, n, unit = m.group(2), int(m.group(3)), _PARAM_UNIT[m.group(2)]
        have = {"temperature": ctx.temp, "oxygen": ctx.oxygen, "oceans": ctx.oceans, "venus": ctx.venus}[param] + \
            raises.get(param, 0) * unit
        rate = _param_rate(param, ctx)
        if m.group(1):
            if have > n:
                return 0.0, math.inf
            # Open until the parameter passes n; a hand card needs about HAND_PLAY_DELAY to get played.
            window = ((n - have) // unit + 1) / rate if rate else math.inf
            return min(1.0, window / HAND_PLAY_DELAY), 0.0
        if have >= n:
            return 1.0, 0.0
        wait = math.ceil((n - have) / unit) / rate if rate else math.inf
        return _within(wait, ctx), wait
    m = re.match(r"^tr (\d+)", req)
    if m:
        need = int(m.group(1)) - ctx.me["terraformRating"]
        if need <= 0:
            return 1.0, 0.0
        wait = need / (ctx.pace / len(ctx.players))  # your fair share of the table's terraforming
        return _within(wait, ctx), wait
    met, _ = requirement_status(req, ctx, extra_tags)
    if met is True:
        return 1.0, 0.0
    return UNCHECKED_REQ_P, (HAND_PLAY_DELAY if met is False else 0.0)


def _card_cost(model):
    return model.get("calculatedCost", (data.card(model["name"]) or {}).get("cost") or 0)


def _money(ctx):
    """M€ you can still spend this game: what you hold plus income at each spendable production phase.
    Steel and titanium count at full value, as if every card could use them."""
    me = ctx.me
    income = me.get("terraformRating", 20) + me.get("megaCreditProduction", 0) + \
        me.get("steelProduction", 0) * ctx.steel + me.get("titaniumProduction", 0) * ctx.titanium
    held = me.get("megaCredits", 0) + me.get("steel", 0) * ctx.steel + me.get("titanium", 0) * ctx.titanium
    return held + income * ctx.phases


def _hand_play(model, ctx, cards, afford, without=None, extra_tags=(), raises=None):
    """(chance, wait) that one hand card gets played, with `without`'s tags left out of the hand."""
    others = [t for c in cards if c is not model and c["name"] != without for t in _kept_tags(c["name"])]
    p, wait = afford, 0.0
    for req in (data.card(model["name"]) or {}).get("req", []):
        rp, rw = _req_timing(req, ctx, extra_tags=extra_tags, hand_tags=others, raises=raises)
        p, wait = p * rp, max(wait, rw)
    return p, wait


def planned_tableau(ctx):
    """Hand project cards as future plays: [{"name", "p", "wait", "model"}], cached on ctx.

    p is the chance the card is played before the game ends: an affordability share (HAND_BUDGET_SHARE of
    your remaining money over the hand's total cost, at most 1) times the chance each requirement is met in
    time. wait is the generations until its requirements are met."""
    if getattr(ctx, "_planned", None) is not None:
        return ctx._planned
    cards = [c for c in ctx.hand if (data.card(c["name"]) or {}).get("type") in PROJECT]
    total = sum(_card_cost(c) for c in cards)
    ctx._afford = 1.0 if total <= 0 else max(0.0, min(1.0, HAND_BUDGET_SHARE * _money(ctx) / total))
    ctx._planned = []
    for c in cards:
        p, wait = _hand_play(c, ctx, cards, ctx._afford)
        ctx._planned.append({"name": c["name"], "p": p, "wait": wait, "model": c})
    return ctx._planned


def _matches(plan, event, ctx, kept=False):
    """[(expected count, generations until it happens)] for an event over the planned plays and future draws.
    `kept` counts only tags that stay on the tableau (for VP per tag)."""
    out = []
    for pc in plan:
        if kept:
            n = _kept_tags(pc["name"]).count(event[4:]) if event.startswith("tag:") else 0
        else:
            n = _play_counts(pc["name"]).get(event, 0)
        if n and pc["p"]:
            out.append((n * pc["p"], pc["wait"] + HAND_PLAY_DELAY))
    future = future_matches(ctx, event)
    if future:
        out.append((future, ctx.gens_left / 2))  # spread evenly over the rest of the game
    return out


def _plan_payout(kind, n, owner, ctx, delay):
    """_payout for an occurrence `delay` generations from now: production pays for fewer phases."""
    if kind.startswith("prod:"):
        res = kind[5:]
        phases = ctx.plant_phases if res == "plants" else ctx.phases
        return n * _unit(res, ctx) * max(0.0, phases - delay)
    return _payout(kind, n, owner, ctx)


def _self_counts(v):
    """Events this card sets off for its own 'including this' effect."""
    counts = dict(getattr(v, "trigger_counts", {}))
    if (v.info or {}).get("type") not in PROJECT:
        # A corporation's printed tags count as played when it enters the game.
        for t in set(v.persistent_tags):
            counts[f"tag:{t}"] = v.persistent_tags.count(t)
        counts["tag:bio"] = sum(v.persistent_tags.count(t) for t in ("plant", "animal", "microbe"))
    return counts


def _discount_event(d):
    if not d.get("tag"):
        return "card"
    return f"card:{d['tag']}" if d.get("per") == "card" else f"tag:{d['tag']}"


def _plan(v, ctx, nested=False):
    """Price this card's combos with the planned tableau, as its marginal value: only pairs that involve
    this card, with this card left out of the plan, and nothing _own_triggers already priced."""
    plan = [pc for pc in planned_tableau(ctx) if pc["name"] != v.name]
    beh = data.behavior(v.name) or {}
    owned = v.name in ctx.tableau

    # This card's own effect on later plays.
    if v.name in OWN_TRIGGERS and not owned:
        self_counts = _self_counts(v) if _SELF_TRIGGER.search((v.info or {}).get("text", "")) else {}
        amount, hand, own = 0.0, 0.0, 0.0
        for event, pays, _ in OWN_TRIGGERS[v.name]:
            items = _matches(plan, event, ctx)
            if self_counts.get(event):
                items.append((self_counts[event], 0.0))
                own += self_counts[event]
            hand += sum(n for n, _ in items)
            amount += sum(_plan_payout(k, amt * n, v.name, ctx, delay) for n, delay in items for k, amt in pays)
        label = f"effect ×{hand:.1f}" + (f" (incl. {own:g} own)" if own else "") if hand else "effect: no planned matches"
        v.add_combo(label, amount, keep=True)

    discount = beh.get("cardDiscount")
    if discount:
        for d in discount if isinstance(discount, list) else [discount]:
            n = sum(n for n, _ in _matches(plan, _discount_event(d), ctx))
            v.add_combo(f"discount {d.get('amount', 0)}" + (f"/{d['tag']}" if d.get("tag") else "") + f" ×{n:.1f}",
                        d.get("amount", 0) * n, keep=True)

    vp = beh.get("vp")
    if isinstance(vp, dict) and "tag" in vp:
        n = sum(n for n, _ in _matches(plan, f"tag:{vp['tag']}", ctx, kept=True))
        v.add_combo(f"{vp['tag']} tags planned ×{n:.1f}", n / (vp.get("per") or 1) * VP)

    # The reverse direction: effect cards in hand (and VP-per-tag cards anywhere) that this card feeds.
    counts = getattr(v, "trigger_counts", None) or _play_counts(v.name)
    fed, amount = [], 0.0
    holders = [{"name": n, "p": 1.0, "wait": 0.0, "tableau": True} for n in ctx.tableau if n != v.name] + plan
    for pc in holders:
        got = 0.0
        if not pc.get("tableau"):
            for event, pays, _ in OWN_TRIGGERS.get(pc["name"], []):
                n = counts.get(event, 0)
                got += sum(_plan_payout(k, amt * n, pc["name"], ctx, pc["wait"]) for k, amt in pays) * pc["p"] * ORDER_SHARE
            d_beh = (data.behavior(pc["name"]) or {}).get("cardDiscount")
            for d in (d_beh if isinstance(d_beh, list) else [d_beh] if d_beh else []):
                got += d.get("amount", 0) * counts.get(_discount_event(d), 0) * pc["p"] * ORDER_SHARE
        h_vp = (data.behavior(pc["name"]) or {}).get("vp")
        if isinstance(h_vp, dict) and "tag" in h_vp:
            got += v.persistent_tags.count(h_vp["tag"]) / (h_vp.get("per") or 1) * VP * pc["p"]
        if got > 0.05:
            fed.append(pc["name"])
            amount += got
    if fed:
        v.add_combo("feeds " + ", ".join(fed), amount)

    if not nested:
        _unlocks(v, ctx)


def _unlocks(v, ctx):
    """Hand cards whose requirement this card helps meet, priced by how much earlier they can be played."""
    cards = [pc["model"] for pc in planned_tableau(ctx)]
    sim = getattr(v, "sim", None) or {}
    raises = {"temperature": sim.get("temperature", 0), "oxygen": sim.get("oxygen", 0), "venus": sim.get("venus", 0),
              "oceans": sim.get("ocean", 0)}
    for model in cards:
        name = model["name"]
        if name == v.name or not (data.card(name) or {}).get("req"):
            continue
        p0, w0 = _hand_play(model, ctx, cards, ctx._afford, without=v.name)
        p1, w1 = _hand_play(model, ctx, cards, ctx._afford, without=v.name, extra_tags=v.persistent_tags, raises=raises)
        if p1 <= p0 + 1e-9 and w1 >= w0 - 1e-9:
            continue
        y = value_card(name, ctx, model=model, nested=True)
        per_phase = sum(n * _unit(r, ctx) for r, n in y.prod.items())

        def worth(p, wait):
            return p * max(0.0, y.net - per_phase * min(wait, ctx.phases)) if p else 0.0
        gain = worth(p1, w1) - worth(p0, w0)
        if gain > 0.05:
            sooner = "" if not p0 else f" ~{w0 - w1:.1f} gen sooner"
            v.add_combo(f"unlocks {name}{sooner}", gain)


# --------------------------------------------------------------------------------------------- award funding

AWARD_FEES = (8, 14, 20)
_CARD_COUNT_METRICS = {"automated", "active", "events", "projects_events", "projects", "blue_green", "reqcards",
                       "cost20", "cost10", "notags"}
# Spread of the final score per generation left, by how easily the count moves: production rarely drops,
# counts of cards, tags and tiles grow in bursts, and stock can be spent at any time.
_SPREAD = {"narrow": 0.4, "medium": 0.8, "wide": 1.5}
# Played cards that raise a production count by themselves: (resource, rough steps per generation).
_AUTO_PRODUCTION = {
    "Botanical Experience": ("plants", 1 / 3),
    "Immigrant City": ("megacredits", 0.7),
    "Tharsis Republic": ("megacredits", 0.5),
    "Saturn Systems": ("megacredits", 0.3),
    "Poseidon": ("megacredits", 0.4),
}
_SAMPLES = 1000


def _metric_kind(metric):
    if metric.startswith("stock:") or metric == "hand":
        return "wide"
    if metric.startswith("prod:"):
        return "narrow"
    return "medium"


def _award_rate(name, metric, color, score, ctx, history):
    """Growth per generation: this seat's stored standings (up to 3 generations back) blended with the
    average so far, which counts setup (corporation, preludes) as one generation."""
    gen = ctx.generation
    if metric == "tr":
        # Everyone starts at 20 TR (14 solo); assume at least a fair share of the table's pace.
        base = 14 if len(ctx.players) == 1 else 20
        average = max((score - base) / gen, ctx.pace / len(ctx.players))
    else:
        average = score / (gen + 1)
    past = [(int(g), s[name][color]) for g, s in (history or {}).items()
            if gen - 3 <= int(g) < gen and color in (s.get(name) or {})]
    if not past:
        return average
    g0, s0 = min(past)
    weight = (gen - g0) / 3
    return weight * max(0.0, (score - s0) / (gen - g0)) + (1 - weight) * average


def _auto_growth(metric, player):
    """Steps per generation the player's played cards add to this count without further plays."""
    out = 0.0
    for card in player.get("tableau") or []:
        name = card["name"]
        if metric.startswith("res:") or metric == "card_resources":
            beh = data.behavior(name) or {}
            rtype = beh.get("resourceType")
            if not rtype or (metric.startswith("res:") and rtype not in metric[4:].split(",")):
                continue
            add = (beh.get("action") or {}).get("addResources")
            out += add if isinstance(add, (int, float)) else (0.5 if beh.get("triggers") else 0)
        elif metric.startswith("prod:") and name in _AUTO_PRODUCTION:
            res, rate = _AUTO_PRODUCTION[name]
            keys = metric[5:]
            if keys == "all" or (keys == "nonmc" and res != "megacredits") or res in keys.split(","):
                out += rate
    return out


def _hand_bump(metric, player, ctx):
    """Cards in hand that could still raise a card-count or tag award: yours exactly, rivals' estimated."""
    tags = metric[4:].split(",") if metric.startswith("tag:") else metric[5:].split(",") if metric.startswith("tags:") else None
    if tags is None and metric not in _CARD_COUNT_METRICS:
        return 0.0
    if player["color"] == ctx.me["color"]:
        hits = 0
        for c in ctx.hand:
            info = data.card(c["name"]) or {}
            if tags is not None:
                hits += 0 if info.get("type") == "event" else sum(info.get("tags", []).count(t) for t in tags)
            else:
                hits += 1 if info.get("type") in ("automated", "active", "event") else 0
        return 0.6 * hits
    hand = player.get("cardsInHandNbr") or 0
    if tags is None:
        return 0.25 * hand
    have = player.get("tags") or {}
    total = sum(n for t, n in have.items() if t != "event") or 1
    share = max(0.05, sum(have.get(t, 0) for t in tags) / total)
    return 0.5 * share * hand


def award_outlook(award, ctx, history=None, seed=0):
    """Project an award's final standings and what funding it is worth to you, in VP.

    Each player's final score is their current score plus their growth rate (and what their played cards
    add by themselves) over the generations left, plus cards in hand that could still count. A small
    Monte Carlo around that, with the app's tie rules, gives the chance of finishing first or second.
    """
    metric = _AWARD_METRICS.get(award["name"])
    scores = {s["color"]: s["score"] for s in award.get("scores", [])}
    if not metric or ctx.me["color"] not in scores:
        return None
    kind = _metric_kind(metric)
    players = {p["color"]: p for p in ctx.players}
    proj = {}
    for color, score in scores.items():
        p = players.get(color, {})
        rate = _award_rate(award["name"], metric, color, score, ctx, history) + _auto_growth(metric, p)
        # Stock and hands get spent along the way, so only half their past growth is assumed to stick.
        mean = score + rate * ctx.gens_left * (0.5 if kind == "wide" else 1) + _hand_bump(metric, p, ctx)
        sigma = _SPREAD[kind] * math.sqrt(ctx.gens_left) * (1 + rate) + (0.4 * score if kind == "wide" else 0)
        proj[color] = (mean, sigma)
    if max(m for m, _ in proj.values()) < 1:
        return None  # nobody has started on it: nothing to project yet
    rng = random.Random(f"{award['name']}:{seed}")
    points = {c: 0.0 for c in scores}
    first = {c: 0 for c in scores}
    second = {c: 0 for c in scores}
    for _ in range(_SAMPLES):
        final = {c: max(0, round(rng.gauss(m, s))) for c, (m, s) in proj.items()}
        for c, pts in _award_points(final, len(ctx.players)).items():
            points[c] += pts
            first[c] += pts == 5
            second[c] += pts == 2
    points = {c: n / _SAMPLES for c, n in points.items()}
    me = ctx.me["color"]
    rivals = [c for c in scores if c != me]

    def standing(c):
        p = players.get(c, {})
        return (p.get("victoryPointsBreakdown") or {}).get("total", p.get("terraformRating", 0))

    leader = max(rivals, key=standing) if rivals else None
    others = max(1, len(ctx.players) - 1)
    gift = sum(points[c] * (1 if c == leader else 1 / others) for c in rivals)
    funded = sum(1 for a in ctx.game.get("awards") or [] if a.get("playerName"))
    fee = AWARD_FEES[funded] / VP if funded < len(AWARD_FEES) else None
    rival_p1 = max((first[c] / _SAMPLES for c in rivals), default=0.0)
    fund = points[me] - gift - fee if fee is not None else None
    # A rival likely to win it will probably fund it: you then get your share without paying the fee.
    wait = rival_p1 * (points[me] - gift)
    return {
        "name": award["name"], "current": scores, "metric": metric, "kind": kind, "projection": proj, "points": points,
        "p1": first[me] / _SAMPLES, "p2": second[me] / _SAMPLES, "gift": gift, "fee": fee,
        "fund": fund, "wait": wait, "rival_p1": rival_p1,
        "top_rival": max(rivals, key=lambda c: points[c]) if rivals else None,
    }


def describe_award(o, ctx):
    """One line: projected finish for you and the two strongest rivals, then funding vs waiting."""
    me = ctx.me["color"]
    rivals = [c for c in o["current"] if c != me and o["projection"][c][0] >= 0.5]
    order = [me] + sorted(rivals, key=lambda c: -o["projection"][c][0])[:2]
    parts = [("you" if c == me else ctx.names.get(c, c)) + f" {o['current'][c]}→~{o['projection'][c][0]:.0f}"
             for c in order]
    line = ", ".join(parts) + f" · P(1st) {o['p1']:.0%}"
    if o["p2"] >= 0.05:
        line += f", P(2nd) {o['p2']:.0%}"
    if o["fund"] is not None:
        top = o["top_rival"]
        line += f" · fund EV {o['fund']:+.1f} VP"
        if top is not None and o["points"][top] >= 0.05:
            line += f" (gives {ctx.names.get(top, top)} ~{o['points'][top]:.1f})"
        line += f" · wait {o['wait']:+.1f}"
        if o["fund"] > max(o["wait"], 0) + 0.3:
            line += " → fund"
        elif o["wait"] > 0.3 and o["wait"] >= o["fund"]:
            line += " → let a rival fund"
        elif o["fund"] < 0:
            line += " → don't fund"
    if o["kind"] == "wide":
        line += " · counts stock or hand: can be spent"
    return line


def _rival_triggers(v, ctx):
    sim = getattr(v, "sim", None) or {}
    hits = {"venus": sim.get("venus", 0) > 0, "colony": v.colonies > 0, "greenery": sim.get("greenery", 0) > 0,
            "city": sim.get("city", 0) > 0, "ocean": sim.get("ocean", 0) > 0,
            "jovian": "jovian" in v.persistent_tags + v.event_tags,
            "microbe": "microbe" in v.persistent_tags + v.event_tags}
    for p in ctx.players:
        for card in p.get("tableau", []):
            trig = ANY_PLAYER_TRIGGERS.get(card["name"])
            if trig and hits.get(trig[0]):
                who = "your" if p["color"] == ctx.me["color"] else f"{p['name']}'s"
                # Priced in _Sim.finish (Exploitation) and _own_triggers (your own cards).
                if card["name"] == "Exploitation Of Venus" or (who == "your" and card["name"] in OWN_TRIGGERS):
                    continue
                v.flags.append(f"triggers {who} {card['name']}: {trig[1]}")
            elif p["color"] != ctx.me["color"]:
                beh = data.behavior(card["name"]) or {}
                if any(t.endswith("ByAnyPlayer") for t in beh.get("triggers", [])) and card["name"] not in ANY_PLAYER_TRIGGERS:
                    v.flags.append(f"{p['name']}'s {card['name']} reacts to other players' plays: check whether this triggers it")


def _attack(v, ctx):
    notes = []
    for p in ctx.rivals:
        corruption = (p.get("underworldData") or {}).get("corruption", 0)
        names = {c["name"] for c in p.get("tableau", [])}
        bits = [f"{p['plants']} plants"]
        if corruption:
            bits.append(f"{corruption} corruption (can block)")
        if "Botanical Experience" in names:
            bits.append("loses only half its plants")
        notes.append(f"{p['name']}: " + ", ".join(bits))
    v.flags.append("attack: " + "; ".join(notes))


# --------------------------------------------------------------------------------------------- output

def describe(v, where=""):
    ratio = f"{v.ratio:.2f}" if v.ratio is not None else "n/a"
    paid = f"pay {v.paid:g}" + (f" ({v.cost:g} + {BUY_COST} to buy)" if v.paid != v.cost else "")
    head = f"{v.name}{' [' + where + ']' if where else ''} — {paid} · value ≈{v.value:.0f} · net {v.net:+.0f} · ratio {ratio}"
    lines = [head]
    if v.parts:
        lines.append("    " + "; ".join(f"{label} {amt:+.1f}" for label, amt in v.parts))
    if v.combo:
        lines.append(f"    combo {sum(a for _, a in v.combo):+.1f}: " + "; ".join(f"{label} {amt:+.1f}" for label, amt in v.combo))
    for f in v.flags:
        lines.append(f"    ⚑ {f}")
    for m in v.manual:
        lines.append(f"    ? {m}")
    return lines
