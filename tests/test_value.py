"""Checks for tfm value against small hand-built game views. Run: python3 -m unittest discover tests"""
import unittest
from contextlib import contextmanager

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

    def test_game_length_cap_matches_our_tables(self):
        # With Prelude, our 4-player games ended in generation 8 and 5-player games in generation 7.
        self.assertEqual(value.Outlook(view(generation=3, temperature=-30, oxygen=0, oceans=0)).by_length, 6)
        self.assertEqual(value.Outlook(view(generation=3, temperature=-30, oxygen=0, oceans=0, players=5)).by_length, 5)

    def test_heat_is_dead_after_max_temperature_unless_ambient(self):
        v = view(temperature=8)
        self.assertEqual(value.Outlook(v, gens_left=3).heat, 0.0)
        v["thisPlayer"]["tableau"] = [{"name": "Ambient"}]
        ctx = value.Outlook(v, gens_left=3)
        self.assertAlmostEqual(ctx.heat, ctx.tr / 8)

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
        # Tying first today would be +3 VP (15 M€); with generations left the lead can still change hands, so the
        # expected gain at game end is positive but smaller.
        amount = dict(v.parts)["Cultivator award (expected at game end)"]
        self.assertGreater(amount, 0)
        self.assertLess(amount, 15)

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
        self.assertTrue(any(label == "unlocks Space Hotels" and amount > 0 for label, amount in v.combo), v.combo)

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


def hand(*names):
    return [{"name": n} for n in names]


UNRELATED = hand("Mine", "Power Plant", "Asteroid")


@contextmanager
def draws(fn):
    """Replace the future-draws hook (tfm/deck.py) for tests about the hand alone."""
    original = value.future_matches
    value.future_matches = fn
    try:
        yield
    finally:
        value.future_matches = original


def no_draws():
    return draws(lambda ctx, event: 0.0)


class PlannedTableau(unittest.TestCase):
    def worth(self, name, cards, **kw):
        return value.value_card(name, value.Outlook(view(hand=cards, **kw)), buying=True)

    def assertCombo(self, name, matching, margin, **kw):
        with_combo, plain = self.worth(name, matching, **kw), self.worth(name, UNRELATED, **kw)
        self.assertGreater(with_combo.value, plain.value + margin, (with_combo.combo, plain.combo))
        return with_combo, plain

    def test_arklight_counts_plant_cards_in_hand(self):
        v, plain = self.assertCombo("Arklight", hand("Lichen", "Grass", "Heather"), 6)
        # 3 plant tags + its own animal tag, 1 VP per 2 animals.
        self.assertAlmostEqual(v.value - plain.value, 3 * value.VP / 2)

    def test_point_luna_counts_earth_cards_in_hand(self):
        self.assertCombo("Point Luna", hand("Sponsors", "Earth Office", "Media Group"), 9)
        with no_draws():
            v, _ = self.assertCombo("Point Luna", hand("Sponsors", "Earth Office", "Media Group"), 9)
        self.assertEqual(v.combo, [("effect ×4.0 (incl. 1 own)", 4 * value.CARD)])

    def test_ecological_zone_counts_animal_and_plant_cards(self):
        self.assertCombo("Ecological Zone", hand("Small Animals", "Lichen", "Grass"), 6)

    def test_tag_discount_counts_matching_hand(self):
        self.assertCombo("Earth Office", hand("Sponsors", "Media Group", "Space Hotels"), 6)
        with no_draws():
            v, plain = self.assertCombo("Earth Office", hand("Sponsors", "Media Group", "Space Hotels"), 6)
        self.assertEqual(plain.combo, [("discount 3/earth ×0.0", 0.0)])

    def test_general_discount_counts_every_project_card(self):
        with no_draws():
            v = self.worth("Earth Catapult", UNRELATED)
        self.assertIn(("discount 2 ×3.0", 6.0), v.combo)

    def test_priced_effect_replaces_the_unknown_note(self):
        v = self.worth("Point Luna", UNRELATED)
        self.assertFalse(any("ongoing effect" in m for m in v.manual), v.manual)
        self.assertEqual(len([l for l in value.describe(v) if "combo" in l]), 1)

    def test_card_in_hand_is_not_counted_twice(self):
        # Valuing a hand card leaves it out of the plan: its own tags count once, as its own.
        offered = self.worth("Ecological Zone", [])
        in_hand = self.worth("Ecological Zone", hand("Ecological Zone"))
        self.assertAlmostEqual(offered.value, in_hand.value)

    def test_unaffordable_hand_counts_less(self):
        cards = hand("Lichen", "Grass", "Heather")
        rich = value.value_card("Arklight", value.Outlook(view(hand=cards), gens_left=4))
        poor = value.value_card("Arklight", value.Outlook(view(hand=cards + hand("Giant Ice Asteroid") * 4), gens_left=4))
        self.assertLess(poor.value, rich.value)

    def test_requirement_out_of_reach_counts_nothing(self):
        # Fish needs +2 °C: 13 steps away, not reached in the 2 generations left.
        ctx = value.Outlook(view(hand=hand("Fish")), gens_left=2)
        self.assertEqual(value.planned_tableau(ctx)[0]["p"], 0.0)
        with no_draws():
            self.assertEqual(value.value_card("Arklight", ctx).combo, [("effect ×1.0 (incl. 1 own)", value.VP / 2)])

    def test_requirement_met_at_current_pace(self):
        ctx = value.Outlook(view(temperature=-20, hand=hand("Grass")), gens_left=5)
        pc = value.planned_tableau(ctx)[0]
        self.assertEqual(pc["p"], 1.0)
        self.assertGreater(pc["wait"], 0)

    def test_reverse_feeds_effect_card_in_hand(self):
        v = self.worth("Asteroid", hand("Media Group"))
        self.assertIn(("feeds Media Group", 3 * value.ORDER_SHARE), v.combo)
        self.assertEqual(self.worth("Asteroid", []).combo, [])

    def test_reverse_vp_per_tag_in_hand(self):
        v = self.worth("Io Mining Industries", hand("Ganymede Colony"))
        self.assertIn(("feeds Ganymede Colony", value.VP), v.combo)

    def test_vp_per_tag_counts_planned_tags(self):
        with no_draws():
            v = self.worth("Ganymede Colony", hand("Io Mining Industries"))
        self.assertIn(("jovian tags planned ×1.0", value.VP), v.combo)

    def test_unlock_is_worth_more_than_a_hand_that_would_unlock_it_anyway(self):
        # Luna Governor's Earth tags could also meet Space Hotels' requirement, but later and less surely.
        def worth(cards):
            return value.value_card("Sponsors", value.Outlook(view(hand=cards, tags={"earth": 1}), gens_left=6))
        alone, covered = worth(hand("Space Hotels")), worth(hand("Space Hotels", "Luna Governor"))
        unlock = lambda v: sum(a for label, a in v.combo if label.startswith("unlocks Space Hotels"))
        self.assertGreater(unlock(alone), unlock(covered))
        self.assertGreater(unlock(covered), 0)

    def test_future_matches_hook_feeds_effects(self):
        # The real hook counts future draws from the deck (tests/test_deck.py checks the numbers).
        ctx = value.Outlook(view())
        self.assertGreater(value.future_matches(ctx, "tag:earth"), 0.0)
        self.assertGreater(value.future_matches(ctx, "ocean"), 0.0)
        self.assertEqual(value.future_matches(ctx, "standard_project"), 0.0)
        with no_draws():
            base = self.worth("Point Luna", []).value
        with draws(lambda ctx, event: 2.0 if event == "tag:earth" else 0.0):
            self.assertAlmostEqual(self.worth("Point Luna", []).value, base + 2 * value.CARD)



def me(vw, **fields):
    vw["thisPlayer"].update(fields)
    return vw


def action_part(v):
    return next(amount for label, amount in v.parts if label.startswith("action ×"))


class LiveGameFixes(unittest.TestCase):
    """Estimates two agent seats found wrong in a live 3-player game (g506b18d8ce00)."""

    # --- requirements and production given up
    def test_production_to_give_up_is_a_requirement(self):
        # Noctis City lowers energy production 1 step (custom code in the app).
        v = value.value_card("Noctis City", value.Outlook(me(view(), energyProduction=0)))
        self.assertIn("NOT PLAYABLE YET: needs 1 energy production to give up (have 0)", v.flags)
        self.assertTrue(any(label.startswith("city tile") for label, _ in v.parts), v.parts)
        v = value.value_card("Noctis City", value.Outlook(me(view(), energyProduction=1)))
        self.assertFalse(any(f.startswith("NOT PLAYABLE") for f in v.flags), v.flags)

    def test_underground_token_requirement(self):
        ctx = value.Outlook(view())
        self.assertEqual(value.requirement_status("undergroundTokens 3", ctx)[0], False)
        ctx = value.Outlook(me(view(), underworldData={"corruption": 0, "tokens": [{"token": "nothing"}] * 3}))
        self.assertEqual(value.requirement_status("undergroundTokens 3", ctx)[0], True)
        self.assertEqual(value.requirement_status("2 titanium production", value.Outlook(me(view(), titaniumProduction=2)))[0], True)

    # --- penalties
    def test_preservation_program_prices_the_skipped_tr(self):
        ctx = value.Outlook(view(), gens_left=8)
        v = value.value_card("Preservation Program", ctx)
        # 5 TR now; a TR skipped g generations from now loses 1 VP and the income phases after it.
        self.assertAlmostEqual(dict(v.parts)["skips your first TR each generation ×8"], -(8 * 5 + 8 * 7 / 2))
        self.assertAlmostEqual(v.value, 5 * ctx.tr - (8 * 5 + 8 * 7 / 2))
        self.assertFalse(any("custom code" in m for m in v.manual), v.manual)

    def test_pharmacy_union_starts_with_two_diseases(self):
        v = value.value_card("Pharmacy Union", value.Outlook(view()))
        self.assertIn(("-8 megacredits", -8), v.parts)

    def test_prelude_megacredits_count_once(self):
        # Donation's 21 M€ is both its startingMC and a stock behavior in the exported data.
        self.assertAlmostEqual(value.value_card("Donation", value.Outlook(view())).value, 21)

    def test_industrial_complex_raises_low_productions(self):
        ctx = value.Outlook(view(), gens_left=8)
        v = value.value_card("Industrial Complex", ctx)
        expected = -18 + 7 * (1 + ctx.steel + ctx.titanium + ctx.energy + ctx.heat) + 8 * ctx.plant
        self.assertAlmostEqual(v.value, expected)
        rich = {f"{r}Production": 2 for r in ("steel", "titanium", "plant", "energy", "heat")}
        v = value.value_card("Industrial Complex", value.Outlook(me(view(), megacreditProduction=-2, **rich), gens_left=8))
        self.assertAlmostEqual(v.value, -18 + 3 * 7)  # only M€ production is below 1: -2 → 1

    # --- award noise
    def test_hand_award_only_moves_with_cards_drawn(self):
        aw = {"name": "Visionary", "playerName": "p1", "scores": [
            {"color": "red", "score": 2}, {"color": "green", "score": 3}, {"color": "blue", "score": 2},
            {"color": "yellow", "score": 0}]}
        ctx = value.Outlook(view(awards=[aw]))
        for name in ("Dust Seals", "Hadesphere", "Supply Drop"):
            v = value.value_card(name, ctx)
            self.assertFalse(any("Visionary" in label for label, _ in v.parts), (name, v.parts))
            self.assertFalse(any("Visionary" in f for f in v.flags), (name, v.flags))
        v = value.value_card("Business Network", ctx)  # its action draws cards
        self.assertTrue(any("Visionary" in label for label, _ in v.parts), v.parts)

    def test_award_value_is_capped_by_the_end_game_projection(self):
        aw = {"name": "Celebrity", "playerName": "p0", "scores": [
            {"color": "red", "score": 4}, {"color": "green", "score": 4}, {"color": "blue", "score": 4},
            {"color": "yellow", "score": 0}]}
        v = value.value_card("16 Psyche", value.Outlook(view(awards=[aw]), gens_left=5))
        amount = dict(v.parts)["Celebrity award (expected at game end)"]
        self.assertGreater(amount, 0)
        self.assertLess(amount, 5 * value.VP)

    def test_unfunded_awards_are_not_flagged_per_card(self):
        aw = {"name": "Space Baron", "scores": [{"color": c, "score": 0} for c in ("red", "green", "blue", "yellow")]}
        v = value.value_card("16 Psyche", value.Outlook(view(awards=[aw])))
        self.assertFalse(any("Space Baron" in f for f in v.flags), v.flags)

    def test_rival_reaction_is_noted_once_per_output(self):
        vw = view()
        vw["players"][1]["tableau"] = [{"name": "United Nations Mission One"}]
        ctx = value.Outlook(vw)
        for name in ("Asteroid", "Dust Seals", "Mine"):
            v = value.value_card(name, ctx)
            self.assertFalse(any("reacts" in f for f in v.flags), v.flags)
        self.assertEqual(value.notes(ctx), ["⚑ p1's United Nations Mission One reacts to other players' plays: "
                                            "check what triggers it"])

    # --- repeated actions
    def test_resource_conversion_action_needs_three_microbes_per_tr(self):
        ctx = value.Outlook(view(temperature=-30, oxygen=0, oceans=0), gens_left=6)
        v = value.value_card("Nitrite Reducing Bacteria", ctx)
        # Starts with 3 microbes: TR now (5 VP + 5 phases), then 3 adds, then a TR with 1 phase left, then an add.
        self.assertAlmostEqual(action_part(v), 10 + 6)

    def test_energy_actions_need_energy_each_generation(self):
        # Unspent energy turns into heat, so 1 energy production never pays for a 3-energy action.
        flat = view(temperature=-30, oxygen=0, oceans=4)
        v = value.value_card("Water Splitting Plant", value.Outlook(me(flat, energyProduction=1), gens_left=6))
        self.assertFalse(any(label.startswith("action ×") for label, _ in v.parts), v.parts)
        ctx = value.Outlook(me(view(temperature=-30, oxygen=0, oceans=4), energyProduction=3, energy=3), gens_left=6)
        self.assertTrue(action_part(value.value_card("Water Splitting Plant", ctx)) > 0)
        # Energy your played Ironworks already spends is not available again.
        vw = me(view(temperature=-30, oxygen=0, oceans=4), energyProduction=4, energy=4)
        vw["thisPlayer"]["tableau"] = [{"name": "Ironworks"}]
        v = value.value_card("Water Splitting Plant", value.Outlook(vw, gens_left=6))
        self.assertFalse(any(label.startswith("action ×") for label, _ in v.parts), v.parts)

    def test_identified_token_is_dug_once(self):
        vw = view(temperature=-30, oxygen=0, oceans=0)
        vw["game"]["gameOptions"]["boardName"] = "tharsis"
        vw["game"]["spaces"] = [{"id": "10", "tileType": 2, "color": "red"},
                                {"id": "11", "undergroundResource": "plant1production"}]
        ctx = value.Outlook(vw, gens_left=6)
        v = value.value_card("Hadesphere", ctx)
        token = value.token_value("plant1production", ctx)
        expected = token + sum(value.blind_dig_value(value._later(ctx, g)) for g in range(1, 6))
        self.assertAlmostEqual(action_part(v), expected)
        self.assertLess(action_part(v), 6 * token)

    # --- combos and custom code
    def test_hand_city_counts_for_tile_triggers(self):
        vw = me(view(hand=[{"name": "Lava Tube Settlement", "calculatedCost": 15}]), megacredits=40)
        v = value.value_card("Rover Construction", value.Outlook(vw))
        label, amount = v.combo[0]
        self.assertTrue(label.startswith("effect ×") and amount > 0, v.combo)

    def test_custom_code_cards_from_the_table(self):
        ctx = value.Outlook(me(view(), energyProduction=1), gens_left=6)
        steel, ti = 2 * ctx.steel * ctx.phases, ctx.titanium * ctx.phases
        self.assertAlmostEqual(value.value_card("Small Open Pit Mine", ctx).value, max(steel, ti))
        self.assertGreater(value.value_card("Deepmining", ctx).value, ctx.steel * ctx.phases)
        vw = me(view(), energyProduction=1)
        vw["thisPlayer"]["tableau"] = [{"name": "Commercial District"}]
        rw = value.value_card("Robotic Workforce", value.Outlook(vw, gens_left=6))
        self.assertEqual(rw.prod, {"energy": -1, "megacredits": 4})
        self.assertGreater(value.value_card("Oumuamua Type Object Survey", ctx).value, 2 * value.CARD)
        self.assertAlmostEqual(value.value_card("Astra Mechanica", value.Outlook(view(tags={"event": 3}))).value, 2 * value.CARD)
        tracks = {"venus": 0, "earth": 0, "mars": 0, "jovian": 0, "moon": -1}
        self.assertGreater(value.value_card("Kickstarter", value.Outlook(view(pathfinders=tracks))).value, 0)
        for name in ("Small Open Pit Mine", "Deepmining", "Robotic Workforce", "Kickstarter", "Lava Tube Settlement",
                     "Oumuamua Type Object Survey", "Astra Mechanica", "Self-replicating Robots"):
            v = value.value_card(name, ctx)
            self.assertFalse(any("custom code" in m for m in v.manual), (name, v.manual))

    def test_imported_hydrogen_counts_its_plants(self):
        ctx = value.Outlook(view(oceans=4, oxygen=1))
        v = value.value_card("Imported Hydrogen", ctx)
        self.assertIn(("best option (3 plants)", 3 * ctx.plant), v.parts)

    def test_stock_to_lose_is_a_requirement(self):
        v = value.value_card("Shipment to Earth", value.Outlook(view()))
        self.assertTrue(any(f.startswith("NOT PLAYABLE YET: needs 3 plants") for f in v.flags), v.flags)
        v = value.value_card("Shipment to Earth", value.Outlook(me(view(), plants=3, steel=3)))
        self.assertFalse(any(f.startswith("NOT PLAYABLE") for f in v.flags), v.flags)



class CheaperStandardProject(unittest.TestCase):
    """Live game Polar Gravity Link: Energy Saving (15 M€) with one city in play gave +1 energy production to claim
    Energizer, which the Power Plant standard project (11 M€) would also have done."""

    def energy_saving(self, cities, awards=()):
        ms = {"name": "Energizer", "scores": [{"color": "red", "score": 5}]}
        vw = me(view(milestones=[ms], awards=awards), energyProduction=5)
        for i, p in enumerate(vw["players"]):
            p["citiesCount"] = cities if i == 0 else 0
        vw["thisPlayer"] = vw["players"][0]
        ctx = value.Outlook(vw)
        v = value.value_card("Energy Saving", ctx, model={"name": "Energy Saving", "calculatedCost": 15})
        value.flag_cheaper_standard_projects([v], ctx)
        return v

    def test_one_city_is_a_dearer_power_plant(self):
        v = self.energy_saving(cities=1)
        self.assertTrue(any(f.startswith("STANDARD PROJECT does as much for less: Power Plant:SP") for f in v.flags),
                        v.flags)

    def test_many_cities_beat_the_power_plant(self):
        v = self.energy_saving(cities=4)
        self.assertFalse(any(f.startswith("STANDARD PROJECT") for f in v.flags), v.flags)

    def test_a_engineer_counts_production_cards(self):
        v = self.energy_saving(cities=1, awards=[award("A. Engineer", 8, 8, funded_by="p0")])
        self.assertTrue(any(label.startswith("A. Engineer award") for label, _ in v.parts), v.parts)
        self.assertFalse(any(f.startswith("STANDARD PROJECT") for f in v.flags), v.flags)


if __name__ == "__main__":
    unittest.main()
