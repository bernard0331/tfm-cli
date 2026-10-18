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


def _per_card(card, event):
    """How many times one play of `card` fires an OWN_TRIGGERS `event` (as value._trigger_counts counts it)."""
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
    return 0


def is_card_event(event):
    """True for the trigger events a drawn project card can fire. Tile and parameter events (temperature,
    ocean, city, TR...) depend on what the card does, not on its printed traits, so they count as 0 here."""
    return event.startswith(("tag:", "card:")) or event in ("card", "event", "space_event", "cost20", "notags", "onetag")


@lru_cache(maxsize=None)
def _share(modules, event):
    cards = _deck(modules)
    return sum(_per_card(c, event) for c in cards) / len(cards) if cards else 0.0


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
