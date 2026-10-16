"""Checks for tfm value against small hand-built game views. Run: python3 -m unittest discover tests"""
import unittest

from tfm import value


def view(generation=4, temperature=-24, oxygen=1, oceans=4, venus=10, awards=(), milestones=(), pathfinders=None,
         tags=None, hand=(), players=4):
    colors = ["red", "green", "blue", "yellow", "black"][:players]

    def player(color, name):
        return {"color": color, "name": name, "tags": {}, "tableau": [], "citiesCount": 1, "coloniesCount": 0,
                "heat": 0, "plants": 0, "terraformRating": 25, "steelValue": 2, "titaniumValue": 3,
                "underworldData": {"corruption": 0}}

    ps = [player(c, f"p{i}") for i, c in enumerate(colors)]
    ps[0]["tags"] = dict(tags or {})
    return {
        "thisPlayer": ps[0], "players": ps, "cardsInHand": list(hand),
        "game": {
            "generation": generation, "temperature": temperature, "oxygenLevel": oxygen, "oceans": oceans,
            "venusScaleLevel": venus, "awards": list(awards), "milestones": list(milestones),
            "pathfinders": pathfinders, "spaces": [], "globalsPerGeneration": [],
            "gameOptions": {"expansions": {"venus": True, "prelude": True, "pathfinders": pathfinders is not None},
                            "altVenusBoard": False, "requiresVenusTrackCompletion": False},
        },
    }


class Baseline(unittest.TestCase):
    def test_reference_cards_break_even(self):
        ctx = value.Outlook(view())
        for name in ("Release of Inert Gases", "Dust Seals"):
            v = value.value_card(name, ctx, buying=True)
            self.assertAlmostEqual(v.ratio, 1.0, places=2, msg=name)

    def test_production_counts_spendable_phases_only(self):
        ctx = value.Outlook(view(), gens_left=3)
        v = value.value_card("Terraforming Contract", ctx)
        self.assertEqual(ctx.phases, 2)
        self.assertAlmostEqual(v.value, 4 * 2)

    def test_maxed_parameter_gives_no_tr(self):
        ctx = value.Outlook(view(temperature=8))
        self.assertEqual(value.value_card("Asteroid", ctx).tr, 0)


    def test_standard_projects_have_no_purchase_price(self):
        ctx = value.Outlook(view())
        v = value.value_card("Asteroid:SP", ctx, buying=True)
        self.assertEqual(v.paid, 14)
        self.assertAlmostEqual(v.value, 8.5)

    def test_excavation_uses_token_bag(self):
        ctx = value.Outlook(view())
        v = value.value_card("Excavate:SP", ctx)
        self.assertAlmostEqual(v.value, value.blind_dig_value(ctx))
        self.assertGreater(value.best_of_value(ctx, 4), value.blind_dig_value(ctx))


class Context(unittest.TestCase):
    def test_temperature_threshold_and_last_step(self):
        ctx = value.Outlook(view(temperature=-2, oceans=4))
        v = value.value_card("Asteroid", ctx)
        self.assertTrue(any("0°C" in label for label, _ in v.parts))

    def test_award_tie_break_hurts_rivals(self):
        aw = {"name": "Celebrity", "playerName": "p0",
              "scores": [{"color": "red", "score": 4}, {"color": "green", "score": 4},
                         {"color": "blue", "score": 4}, {"color": "yellow", "score": 0}]}
        ctx = value.Outlook(view(awards=[aw]))
        v = value.value_card("16 Psyche", ctx)
        self.assertTrue(any("p1 -3" in f and "p2 -3" in f for f in v.flags), v.flags)

    def test_milestone_claim(self):
        ms = {"name": "Smith", "scores": [{"color": "red", "score": 4}]}
        ctx = value.Outlook(view(milestones=[ms]))
        v = value.value_card("16 Psyche", ctx)
        self.assertTrue(any(f.startswith("MILESTONE: Smith") for f in v.flags), v.flags)

    def test_planetary_track_reward(self):
        ctx = value.Outlook(view(pathfinders={"venus": 7, "earth": 0, "mars": 0, "jovian": 0, "moon": -1}))
        v = value.value_card("Neutralizer Factory", ctx)
        self.assertTrue(any("venus track 8" in label for label, _ in v.parts))

    def test_unmet_requirement(self):
        ctx = value.Outlook(view(oceans=2))
        v = value.value_card("Kelp Farming", ctx)
        self.assertTrue(any(f.startswith("NOT PLAYABLE YET") for f in v.flags))

    def test_unlocks_card_in_hand(self):
        ctx = value.Outlook(view(tags={"earth": 1}, hand=[{"name": "Space Hotels", "calculatedCost": 12}]))
        v = value.value_card("Terraforming Contract", ctx)
        self.assertTrue(any("Space Hotels" in f for f in v.flags), v.flags)

    def test_award_points_tie_rules(self):
        self.assertEqual(value._award_points({"a": 3, "b": 3, "c": 1}, 3), {"a": 5, "b": 5, "c": 0})
        self.assertEqual(value._award_points({"a": 3, "b": 2, "c": 2}, 3), {"a": 5, "b": 2, "c": 2})
        self.assertEqual(value._award_points({"a": 3, "b": 2}, 2), {"a": 5, "b": 0})


if __name__ == "__main__":
    unittest.main()
