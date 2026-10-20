"""Checks for tfm/deck.py (expected future draws). Run: python3 -m unittest discover tests"""
import unittest

from tfm import data, deck, value
from tests.test_value import no_draws, view

BASE = {}  # base + Corporate Era (on by default)


def outlook(expansions=None, gens_left=8, generation=1, hand=()):
    v = view(generation=generation, hand=hand)
    if expansions is not None:
        v["game"]["gameOptions"]["expansions"] = dict(expansions)
    return value.Outlook(v, gens_left=gens_left)


def effect(v):
    """M€ of the valued card's own effect, as value._plan prices it (label "effect ×n")."""
    return sum(amt for label, amt in v.combo if label.startswith("effect"))


def from_draws(name, ctx_fn):
    """The part of a card's effect value that comes from future draws: real hook minus no draws."""
    with_draws = effect(value.value_card(name, ctx_fn()))
    with no_draws():
        without = effect(value.value_card(name, ctx_fn()))
    return with_draws - without


class Shares(unittest.TestCase):
    def test_base_deck_is_the_208_card_project_deck(self):
        cards = deck.deck(BASE)
        self.assertEqual(len(cards), 208)
        self.assertTrue(all(c["module"] in ("base", "corpera") for c in cards))
        self.assertEqual(len(deck.deck({"corpera": False})), len([c for c in data.cards().values()
                         if c["module"] == "base" and c["type"] in deck.PROJECT_TYPES]))

    def test_shares_come_from_the_card_data(self):
        cards = deck.deck(BASE)
        earth = sum(c.get("tags", []).count("earth") for c in cards) / len(cards)
        events = sum(c["type"] == "event" for c in cards) / len(cards)
        big = sum((c.get("cost") or 0) >= 20 for c in cards) / len(cards)
        bio = sum(c.get("tags", []).count(t) for c in cards for t in ("plant", "animal", "microbe")) / len(cards)
        self.assertAlmostEqual(deck.share(BASE, "tag:earth"), earth)
        self.assertAlmostEqual(deck.share(BASE, "event"), events)
        self.assertAlmostEqual(deck.share(BASE, "cost20"), big)
        self.assertAlmostEqual(deck.share(BASE, "tag:bio"), bio)
        for event in ("tag:earth", "card:jovian", "event", "space_event", "cost20", "notags", "onetag", "tag:bio"):
            self.assertGreater(deck.share(BASE, event), 0, event)
        self.assertLessEqual(deck.share(BASE, "space_event"), deck.share(BASE, "event"))

    def test_effect_events_come_from_card_behavior(self):
        # Tiles, steps and TR come from what drawn cards do (their exported behavior); standard projects never.
        for event in ("temperature", "ocean", "city", "tr", "vpcard", "prodmc"):
            self.assertGreater(deck.share(BASE, event), 0.0, event)
        self.assertEqual(deck.share(BASE, "standard_project"), 0.0)
        self.assertGreaterEqual(deck.share(BASE, "tr"), deck.share(BASE, "ocean") + deck.share(BASE, "temperature"))

    def test_expansions_setting_changes_the_deck(self):
        self.assertEqual(deck.share(BASE, "card:venus"), 0.0)
        self.assertGreater(deck.share({"venus": True}, "card:venus"), 0.0)
        self.assertEqual(deck.share(BASE, "tag:moon"), 0.0)
        self.assertGreater(deck.share({"moon": True}, "tag:moon"), 0.0)
        self.assertEqual(len(deck.deck({"venus": True})), 208 + len([c for c in data.cards().values()
                         if c["module"] == "venus" and c["type"] in deck.PROJECT_TYPES]))

    def test_variant_replaces_its_base_card(self):
        names = lambda ex: {c["text"] for c in deck.deck(ex)}  # noqa: E731
        ares = {c["text"] for k, c in data.cards().items() if k.endswith(":ares") and c["type"] in deck.PROJECT_TYPES}
        base_eco = data.cards()["Ecological Zone"]["text"]
        self.assertIn(base_eco, names(BASE))
        self.assertTrue(ares <= names({"ares": True}))
        n_ares = len([k for k in data.cards() if k.endswith(":ares") and data.cards()[k]["type"] in deck.PROJECT_TYPES])
        n_new = len([c for c in data.cards().values() if c["module"] == "ares" and c["type"] in deck.PROJECT_TYPES])
        self.assertEqual(len(deck.deck({"ares": True})), 208 + n_new - n_ares)


class FutureMatches(unittest.TestCase):
    def test_formula(self):
        ctx = outlook(gens_left=8)
        rate = deck.share(ctx.expansions, "tag:earth") * deck.CARDS_SEEN_PER_GEN * deck.PLAYED_SHARE
        self.assertAlmostEqual(value.future_matches(ctx, "tag:earth"), rate * 7)

    def test_no_draws_left_in_the_last_generation(self):
        self.assertEqual(value.future_matches(outlook(gens_left=1), "tag:earth"), 0.0)

    def test_card_counts_every_project_card(self):
        ctx = outlook(gens_left=8)
        self.assertAlmostEqual(value.future_matches(ctx, "card"), deck.CARDS_SEEN_PER_GEN * deck.PLAYED_SHARE * 7)

    def test_point_luna_gains_from_future_earth_cards_and_shrinks(self):
        # Generation 1, no Earth cards in hand.
        gains = [from_draws("Point Luna", lambda: outlook(gens_left=g, hand=[{"name": "Mine"}]))
                 for g in (8, 6, 4, 2, 1)]
        self.assertGreater(gains[0], 0)
        self.assertTrue(all(a > b for a, b in zip(gains, gains[1:])), gains)
        self.assertEqual(gains[-1], 0)
        # Each expected Earth tag draws a card.
        self.assertAlmostEqual(gains[0], value.future_matches(outlook(gens_left=8), "tag:earth") * value.CARD)

    def test_draws_show_in_the_effect_count_on_one_line(self):
        ctx = outlook(gens_left=8)
        v = value.value_card("Media Group", ctx)
        n = value.future_matches(ctx, "event")
        self.assertEqual(v.combo, [(f"effect ×{n:.1f}", n * 3)])
        self.assertFalse(any("ongoing effect" in m for m in v.manual))
        self.assertEqual(len([l for l in value.describe(v) if "combo" in l]), 1)

    def test_production_payouts_discount_late_matches(self):
        # Advertising pays 1 M€ production per 20+ M€ card. Draws are spread over the rest of the game, so
        # they earn fewer phases; two generations left means the only draw comes in the last one.
        self.assertEqual(from_draws("Advertising", lambda: outlook(gens_left=2)), 0)
        n = value.future_matches(outlook(gens_left=6), "cost20")
        self.assertAlmostEqual(from_draws("Advertising", lambda: outlook(gens_left=6)), n * (5 - 6 / 2))

    def test_owner_on_tableau_is_not_double_counted(self):
        # Valuing a different card still prices only that card's own triggers, not Point Luna's.
        ctx = outlook(gens_left=8)
        ctx.tableau["Point Luna"] = {"name": "Point Luna"}
        self.assertEqual(effect(value.value_card("Media Group", ctx)),
                         effect(value.value_card("Media Group", outlook(gens_left=8))))


if __name__ == "__main__":
    unittest.main()
