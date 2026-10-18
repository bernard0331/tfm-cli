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
    def test_vp_reference_card_breaks_even(self):
        ctx = value.Outlook(view())
        v = value.value_card("Dust Seals", ctx, buying=True)
        self.assertAlmostEqual(v.ratio, 1.0, places=2)

    def test_tr_is_one_vp_plus_remaining_income(self):
        for gens_left in (1, 3, 8):
            ctx = value.Outlook(view(), gens_left=gens_left)
            self.assertEqual(ctx.tr, 5 + (gens_left - 1))
            self.assertAlmostEqual(value.value_card("Release of Inert Gases", ctx).value, 2 * ctx.tr)
            self.assertAlmostEqual(ctx.heat, ctx.tr / 8)
            self.assertAlmostEqual(ctx.plant, (5 + ctx.tr) / 8)

    def test_last_generation_tr_is_worth_one_vp(self):
        ctx = value.Outlook(view(), gens_left=1)
        self.assertEqual(ctx.phases, 0)
        self.assertEqual(ctx.tr, 5)

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
        self.assertAlmostEqual(v.value, ctx.tr)

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

    def test_oxygen_bonus_step_places_ocean_at_zero(self):
        ctx = value.Outlook(view(oxygen=7, temperature=-2))
        labels = [label for label, _ in value.value_card("Mining Expedition", ctx).parts]
        self.assertIn("oxygen reaches 8%: bonus temperature step", labels)
        self.assertIn("temperature reaches 0°C: bonus ocean (via oxygen 8%)", labels)

    def test_oxygen_bonus_step_gives_heat_production(self):
        ctx = value.Outlook(view(oxygen=7, temperature=-22))
        labels = [label for label, _ in value.value_card("Mining Expedition", ctx).parts]
        self.assertIn("temperature reaches -20°C: +1 heat production (via oxygen 8%)", labels)

    def test_own_temperature_raise_counts_before_oxygen_bonus(self):
        # Small Comet takes -4 to -2 itself; its oxygen step to 8% then takes -2 to 0 and places an ocean.
        ctx = value.Outlook(view(oxygen=7, temperature=-4))
        labels = [label for label, _ in value.value_card("Small Comet", ctx).parts]
        self.assertIn("temperature reaches 0°C: bonus ocean (via oxygen 8%)", labels)

    def test_oxygen_bonus_needs_temperature_left_after_own_raise(self):
        ctx = value.Outlook(view(oxygen=7, temperature=6))
        v = value.value_card("Small Comet", ctx)
        self.assertFalse(any("bonus temperature step" in label for label, _ in v.parts))
        self.assertIn("oxygen reaches 8% but temperature is maxed: no bonus", v.flags)

    def test_own_ocean_fills_track_before_zero_degree_bonus(self):
        ctx = value.Outlook(view(temperature=-2, oceans=8))
        v = value.value_card("Comet", ctx)
        self.assertFalse(any("bonus ocean" in label for label, _ in v.parts))
        self.assertIn("temperature reaches 0°C but oceans are full: no bonus ocean", v.flags)

    def test_track_reward_venus_step_crosses_threshold(self):
        # Venus track step 8 gives the rising player a Venus step, which takes 14% to 16% (+1 TR).
        ctx = value.Outlook(view(venus=14, pathfinders={"venus": 7, "earth": 0, "mars": 0, "jovian": 0, "moon": -1}))
        labels = [label for label, _ in value.value_card("Sulphur-Eating Bacteria", ctx).parts]
        self.assertIn("venus track 8: you get venus_scale", labels)
        self.assertIn("Venus reaches 16%: +1 TR (via venus track 8)", labels)

    def test_track_greenery_unlocks_gardener(self):
        ms = {"name": "Gardener", "scores": [{"color": "red", "score": 2}]}
        ctx = value.Outlook(view(pathfinders={"earth": 21}, milestones=[ms]))
        v = value.value_card("Sponsors", ctx)
        self.assertIn(("lets you claim Gardener (5 VP for 8 M€)", 17), v.parts)
        self.assertTrue(any(f.startswith("MILESTONE: Gardener 2→3/3") for f in v.flags), v.flags)

    def test_track_greenery_changes_funded_award(self):
        aw = {"name": "Cultivator", "playerName": "p0", "scores": [
            {"color": "red", "score": 2}, {"color": "green", "score": 3},
            {"color": "blue", "score": 1}, {"color": "yellow", "score": 0},
        ]}
        ctx = value.Outlook(view(pathfinders={"earth": 21}, awards=[aw]))
        v = value.value_card("Sponsors", ctx)
        self.assertIn(("Cultivator award position", 15), v.parts)

    def test_track_city_triggers_rival_cards(self):
        vw = view(pathfinders={"mars": 16})
        vw["players"][1]["tableau"] = [{"name": "Rover Construction"}]
        v = value.value_card("Dust Storm", value.Outlook(vw))
        self.assertTrue(any("triggers p1's Rover Construction" in f for f in v.flags), v.flags)

    def test_exploitation_of_venus_pays_the_raiser(self):
        vw = view(venus=10)
        vw["players"][1]["tableau"] = [{"name": "Exploitation Of Venus"}]
        v = value.value_card("Air Scrapping (Var)", value.Outlook(vw))
        self.assertIn(("p1's Exploitation Of Venus pays you per Venus step", 2.0), v.parts)


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


class TrPerTag(unittest.TestCase):
    def test_ganymede_counts_jovian_tags_including_itself(self):
        ctx = value.Outlook(view(tags={"jovian": 3}))
        v = value.value_card("Terraforming Ganymede", ctx)
        self.assertEqual(v.tr, 4)
        self.assertAlmostEqual(v.value, 4 * ctx.tr + 2 * value.VP)
        self.assertFalse(any("custom code" in m for m in v.manual), v.manual)

    def test_social_events_counts_own_mars_tag_on_an_event(self):
        ctx = value.Outlook(view(tags={"mars": 2}))
        self.assertEqual(value.value_card("Social Events", ctx).tr, 1)
        ctx = value.Outlook(view(tags={"mars": 3}))
        self.assertEqual(value.value_card("Social Events", ctx).tr, 2)


def award(name, mine, rival, funded_by=None):
    a = {"name": name, "scores": [{"color": "red", "score": mine}, {"color": "green", "score": rival},
                                  {"color": "blue", "score": 0}, {"color": "yellow", "score": 0}]}
    if funded_by:
        a["playerName"] = funded_by
    return a


class AwardFunding(unittest.TestCase):
    def outlook(self, a, history=None, rival_tableau=(), gens_left=5):
        vw = view(awards=[a])
        vw["players"][1]["tableau"] = [{"name": n} for n in rival_tableau]
        ctx = value.Outlook(vw, gens_left=gens_left)
        return value.award_outlook(a, ctx, history), ctx

    def test_wide_production_lead_is_worth_funding(self):
        history = {"2": {"Banker": {"red": 10, "green": 2}}}
        o, ctx = self.outlook(award("Banker", 16, 4), history)
        self.assertEqual(o["kind"], "narrow")
        self.assertGreater(o["p1"], 0.95)
        self.assertGreater(o["fund"], 1)
        self.assertIn("→ fund", value.describe_award(o, ctx))

    def test_thin_stock_lead_is_not(self):
        o, ctx = self.outlook(award("Miner", 6, 5))
        self.assertEqual(o["kind"], "wide")
        self.assertLess(o["p1"], 0.65)
        self.assertLess(o["fund"], 1)
        self.assertNotIn("→ fund", value.describe_award(o, ctx))

    def test_rival_cards_that_add_animals_overtake_a_lead(self):
        plain, _ = self.outlook(award("Zoologist", 5, 3))
        o, ctx = self.outlook(award("Zoologist", 5, 3), rival_tableau=("Birds", "Fish", "Small Animals"))
        self.assertGreater(o["projection"]["green"][0], o["projection"]["red"][0])
        self.assertLess(o["p1"], plain["p1"])
        self.assertLess(o["p1"], 0.3)
        self.assertGreater(o["wait"], o["fund"])

    def test_measured_growth_moves_the_projection(self):
        a = award("Banker", 12, 12)
        flat, _ = self.outlook(a, {"3": {"Banker": {"red": 12, "green": 6}}})
        self.assertLess(flat["projection"]["red"][0], flat["projection"]["green"][0])

    def test_no_fee_once_three_are_funded(self):
        a = award("Banker", 10, 2)
        vw = view(awards=[a, award("Miner", 1, 1, "p1"), award("Landlord", 1, 1, "p1"), award("Scientist", 1, 1, "p2")])
        o = value.award_outlook(a, value.Outlook(vw, gens_left=3))
        self.assertIsNone(o["fund"])


def with_tableau(*names, **kw):
    vw = view(**kw)
    vw["thisPlayer"]["tableau"] = [{"name": n} for n in names]
    return value.Outlook(vw)


class OwnTriggers(unittest.TestCase):
    def part(self, v, owner):
        return next((amount for label, amount in v.parts if label.startswith(f"your {owner}:")), None)

    def test_temperature_trigger_counts_each_step(self):
        v = value.value_card("Big Asteroid", with_tableau("Homeostasis Bureau", temperature=-20))
        self.assertEqual(self.part(v, "Homeostasis Bureau"), 6)

    def test_track_city_pays_own_city_triggers_once(self):
        ctx = with_tableau("Tharsis Republic", "Pets", pathfinders={"mars": 16})
        v = value.value_card("Dust Storm", ctx)
        self.assertEqual(self.part(v, "Tharsis Republic"), ctx.phases + 3)
        self.assertEqual(self.part(v, "Pets"), value.VP / 2)
        self.assertEqual(sum(amount for label, amount in v.parts if label == "mars track 17: you get city"),
                         value.CITY_TILE)

    def test_tr_trigger_counts_bonus_steps(self):
        # Own oxygen step, then the 8% bonus temperature step, then the 0°C ocean: 3 TR.
        ctx = with_tableau("Terraforming Deal", oxygen=7, temperature=-2)
        self.assertEqual(self.part(value.value_card("Mining Expedition", ctx), "Terraforming Deal"), 6)

    def test_event_and_space_event_triggers(self):
        v = value.value_card("Big Asteroid", with_tableau("Media Group", "Optimal Aerobraking", temperature=-20))
        self.assertEqual(self.part(v, "Media Group"), 3)
        self.assertIsNotNone(self.part(v, "Optimal Aerobraking"))

    def test_standard_project_triggers(self):
        v = value.value_card("Greenery", with_tableau("Standard Technology", "CrediCor", oxygen=3))
        self.assertEqual(self.part(v, "Standard Technology"), 3)
        self.assertEqual(self.part(v, "CrediCor"), 4)

    def test_no_trigger_without_matching_effect(self):
        v = value.value_card("Big Asteroid", with_tableau("Arctic Algae", temperature=-20))
        self.assertIsNone(self.part(v, "Arctic Algae"))


if __name__ == "__main__":
    unittest.main()
