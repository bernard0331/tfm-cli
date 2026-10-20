"""Expected future draws, from the project deck's composition.

`tfm value` prices an effect card from the cards that will trigger it. Approach 1 counts the hand; this module
adds the cards you have not seen yet: how many matching cards you can expect to draw and play in the
generations left, given which expansions are in the game.

Everything here comes from the rules and the card data (tfm/data/cards.json), not from our game results.
"""
from functools import lru_cache

from . import data

PROJECT_TYPES = ("automated", "active", "event")

# Research phase: each player gets 4 new cards per generation (dealt 4, or drafted down to 4) and may buy any
# of them. Drafting shows more cards but you still keep 4, and picking matching cards on purpose is not
# modelled, so this is a floor. Card-draw effects are left out for the same reason.
CARDS_SEEN_PER_GEN = 4

# Of those 4, about 2 get bought and played. Assumption from the economy, not fitted: each card costs 3 M€ to
# buy plus its printed cost (data average ≈ 12 M€, see `mean_cost()`), so about 15 M€ per card played, and a
# player's ~30-40 M€ a generation (TR + M€ production, plus steel/titanium) also pays for standard projects,
# milestones, awards and actions, and for cards already in hand. That leaves room for about 2 new cards.
CARDS_PLAYED_PER_GEN = 2
PLAYED_SHARE = CARDS_PLAYED_PER_GEN / CARDS_SEEN_PER_GEN

COST20 = 20             # "20 M€ or more" triggers (Advertising, CrediCor, Spin-off Department)
BIO_TAGS = ("plant", "animal", "microbe")
# Expansions on by default in the app when a view leaves them out (DEFAULT_EXPANSIONS in GameModule.ts).
DEFAULT_ON = ("corpera",)


def _enabled(expansions):
    on = {"base"} | {m for m in DEFAULT_ON if expansions.get(m, True)}
    return frozenset(on | {m for m, flag in expansions.items() if flag})


@lru_cache(maxsize=None)
def _names(modules):
    """Names of the project cards in a game with these modules. A variant such as "Ecological Zone:ares"
    replaces its base card when its module is in, as the app's GameCards does."""
    cards = {k: c for k, c in data.cards().items() if c.get("type") in PROJECT_TYPES and c.get("module") in modules}
    replaced = {k.split(":")[0] for k in cards if ":" in k}
    return tuple(k for k in cards if k not in replaced)


@lru_cache(maxsize=None)
def _deck(modules):
    return tuple(data.cards()[k] for k in _names(modules))


def deck(expansions):
    """Project cards in the deck for a `gameOptions.expansions` dict."""
    return _deck(_enabled(expansions or {}))


def names(expansions):
    """Names of the project cards in the deck for a `gameOptions.expansions` dict."""
    return _names(_enabled(expansions or {}))


def _per_card(card, event, name=""):
    """How many times one play of `card` (named `name`) fires an OWN_TRIGGERS `event` (as value._trigger_counts
    counts it)."""
    tags = card.get("tags") or []
    kind = card.get("type")
    if event.startswith("tag:"):
        t = event[4:]
        return sum(tags.count(b) for b in BIO_TAGS) if t == "bio" else tags.count(t)
    if event == "card":
        return 1
    if event.startswith("card:"):
        return 1 if event[5:] in tags else 0
    if event == "event":
        return 1 if kind == "event" else 0
    if event == "space_event":
        return 1 if kind == "event" and "space" in tags else 0
    if event == "cost20":
        return 1 if (card.get("cost") or 0) >= COST20 else 0
    if event == "notags":
        return 1 if not tags else 0
    if event == "onetag":
        return 1 if len(tags) == 1 else 0
    if event == "multitag":
        # Spire counts an event's own event tag too.
        return 1 if len(tags) + (kind == "event") >= 2 else 0
    if event == "orbital":
        return 1 if "space" in tags and not set(tags) & PLANETARY_TAGS else 0
    if event == "cheapevent":
        return 1 if kind == "event" and (card.get("cost") or 0) <= 14 else 0
    return effect_counts(name).get(event, 0) if name else 0


PLANETARY_TAGS = {"venus", "earth", "mars", "jovian", "moon"}
# M€ per production step by resource, for "production gained" triggers (Manutech): the rates value.py uses with
# a typical game's Outlook (steel 2, titanium 3, a plant ≈ 1.6, heat ≈ 1.3 while temperature is open).
PRODUCTION_UNIT = {"megacredits": 1.0, "steel": 2.0, "titanium": 3.0, "plants": 1.6, "energy": 1.0, "heat": 1.3}
# Trigger events that come from what a card does (its behavior) rather than from its printed traits.
EFFECT_EVENTS = ("city", "ocean", "greenery", "tile", "temperature", "oxygen", "venus", "tr", "colony",
                 "prodmc", "prodcard", "vpcard", "token")


@lru_cache(maxsize=None)
def _effect_counts(name):
    beh = data.behavior(name) or {}
    b = beh.get("behavior") or {}
    steps = b.get("global") or {}
    num = lambda x: x if isinstance(x, (int, float)) else 0  # noqa: E731
    oceans = (b["ocean"].get("count", 1) if isinstance(b["ocean"], dict) else 1) if "ocean" in b else 0
    out = {"city": 1 if "city" in b else 0, "ocean": oceans, "greenery": 1 if "greenery" in b else 0,
           "temperature": num(steps.get("temperature")), "oxygen": num(steps.get("oxygen")) + ("greenery" in b),
           "venus": num(steps.get("venus")), "colony": 1 if "buildColony" in (b.get("colonies") or {}) else 0}
    out["tile"] = out["city"] + out["ocean"] + out["greenery"] + (1 if "tile" in b else 0)
    out["tr"] = num(b.get("tr")) + oceans + out["temperature"] + out["oxygen"] + out["venus"]
    out["prodmc"] = sum(n * PRODUCTION_UNIT.get(r, 1.0) for r, n in (b.get("production") or {}).items()
                        if isinstance(n, (int, float)) and n > 0)
    out["prodcard"] = 1 if out["prodmc"] else 0
    vp = beh.get("vp")
    out["vpcard"] = 1 if vp is not None and not (isinstance(vp, (int, float)) and vp < 0) else 0
    ex = (b.get("underworld") or {}).get("excavate")
    out["token"] = num(ex if isinstance(ex, (int, float)) else (ex or {}).get("count", 1)) if ex else 0
    return {k: n for k, n in out.items() if n}


def effect_counts(name):
    """How often one play of a card fires each EFFECT_EVENTS trigger, from its exported behavior (bonus steps from
    thresholds and custom code left out)."""
    return _effect_counts(name)


def is_card_event(event):
    """True for the trigger events a drawn project card can fire: its printed traits, and what its exported
    behavior does (tiles, steps, TR, production gained; EFFECT_EVENTS)."""
    return event.startswith(("tag:", "card:")) or event in (
        "card", "event", "space_event", "cost20", "notags", "onetag", "multitag", "orbital", "cheapevent") or \
        event in EFFECT_EVENTS


@lru_cache(maxsize=None)
def _share(modules, event):
    names = _names(modules)
    return sum(_per_card(data.cards()[n], event, n) for n in names) / len(names) if names else 0.0


def share(expansions, event):
    """Expected trigger count per project card drawn: the share of cards with a trait, or tags per card."""
    return _share(_enabled(expansions or {}), event) if is_card_event(event) else 0.0


def mean_cost(expansions):
    cards = deck(expansions)
    return sum(c.get("cost") or 0 for c in cards) / len(cards) if cards else 0.0


def draw_gens(ctx):
    """Research phases still to come. This generation's cards are already dealt (they are in the hand, which
    value.planned_tableau counts), so only the generations after this one bring new cards."""
    return max(0, ctx.gens_left - 1)


def matches_per_gen(ctx, event):
    return share(ctx.game["gameOptions"].get("expansions"), event) * CARDS_SEEN_PER_GEN * PLAYED_SHARE


def future_matches(ctx, event):
    """Expected number of times `event` fires from cards you have not drawn yet, over the rest of the game."""
    return matches_per_gen(ctx, event) * draw_gens(ctx)
