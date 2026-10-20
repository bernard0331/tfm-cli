"""Checks for the problems agent seats found in live games 'Isolated Signal Stream' (4 players, Terra Cimmeria) and
'Massive Optics Charge' (3 players, Utopia Planitia). Run: python3 -m unittest discover tests"""
import unittest

import contextlib
import io
from unittest import mock

from tfm import cli, data, options, plan, score, value
from test_plan import first_gen, game
from test_value import award, view

SATURN_KEEP = ["16 Psyche", "Solar Storm", "Heavy Taxation", "Detective TV Series", "Sub-zero Salt Fish"]


def opening_view(corps=(), preludes=(), projects=()):
    v = game()
    v["dealtCorporationCards"] = [{"name": n} for n in corps]
    v["dealtPreludeCards"] = [{"name": n} for n in preludes]
    v["dealtProjectCards"] = [{"name": n} for n in projects]
    return v


def colonies(v, *tiles):
    """Colony tiles in play: (name, owners, track position)."""
    v["game"]["colonies"] = [{"name": n, "colonies": list(owners), "trackPosition": pos, "isActive": True}
                             for n, owners, pos in tiles]
    return v


class PackageTags(unittest.TestCase):
    """1. Requirements count the whole opening package's tags."""

    def test_value_points_at_the_package_instead_of_not_playable(self):
        v = opening_view(["Saturn Systems"], ["UNMI Contractor", "Donation"], ["Heavy Taxation", "Detective TV Series"])
        flags = value.value_card("Heavy Taxation", value.Outlook(v)).flags
        self.assertFalse(any(f.startswith("NOT PLAYABLE") for f in flags), flags)
        self.assertTrue(any("met if your package includes 2 of UNMI Contractor, Detective TV Series" in f
                            for f in flags), flags)

    def test_plan_plays_the_tag_card_that_unlocks_another(self):
        # Detective TV Series is worth ~0 by itself, but with UNMI Contractor's Earth tag it unlocks Heavy Taxation.
        p = plan.opening(game(), "Saturn Systems", ["UNMI Contractor", "Donation"], SATURN_KEEP)
        self.assertIsNotNone(first_gen(p, "Heavy Taxation"))
        self.assertLessEqual(first_gen(p, "Detective TV Series"), first_gen(p, "Heavy Taxation"))
        p = plan.opening(game(), "Saturn Systems", ["Donation"], ["Heavy Taxation", "Detective TV Series"])
        self.assertIsNone(first_gen(p, "Heavy Taxation"))


class EveryRequirement(unittest.TestCase):
    """2. The simulator respects every requirement it can check and blocks the ones it can't."""

    def test_unreachable_requirements_are_never_played(self):
        # Diversity Support needs 9 resource types; Private Investigator a player with more corruption than you.
        p = plan.opening(game(), "Cheung Shing MARS", [], ["Diversity Support", "Private Investigator"])
        self.assertIsNone(first_gen(p, "Diversity Support"))
        self.assertIsNone(first_gen(p, "Private Investigator"))

    def test_resource_types_and_any_player_requirements(self):
        v = view()
        v["thisPlayer"].update(megacredits=5, steel=1, plants=2)
        ctx = value.Outlook(v)
        self.assertEqual(value.requirement_status("resourceTypes 9", ctx), (False, "resource types 3/9"))
        v["players"][1]["citiesCount"] = 3
        met, text = value.requirement_status("cities 4 (any player)", value.Outlook(v))
        self.assertTrue(met, text)  # 1 + 3 + 1 + 1 cities in play

    def test_unchecked_rival_requirements_wait_for_mid_game(self):
        planner = plan._Planner(game(), 8)
        s = planner.state_from_view()
        self.assertFalse(planner.playable("Martian Culture", s, planner.ctx(s, 0)))  # 2 Mars tags (any player)
        self.assertTrue(planner.playable("Martian Culture", s, planner.ctx(s, 5)))

    def test_volcanic_tile_needs_a_free_volcanic_space(self):
        v = view()
        v["game"]["spaces"] = [{"id": "08", "spaceType": "land", "highlight": "volcanic", "tileType": 2, "color": "blue"},
                               {"id": "09", "spaceType": "land"}]
        flags = value.value_card("Lava Flows:ares", value.Outlook(v)).flags
        self.assertIn("NOT PLAYABLE: volcanic spaces free: none", flags)
        # A board without volcanic spaces (Utopia Planitia) lets the tile go on any land space.
        v["game"]["spaces"] = [{"id": "09", "spaceType": "land"}]
        ok = value.tile_space_status("Lava Flows:ares", value.Outlook(v))
        self.assertEqual(ok, (True, "this board has no volcanic spaces: the tile may go on any land space"))


class CustomCode(unittest.TestCase):
    """3. Custom-code preludes and corporation effects are priced."""

    def test_vital_colony_takes_the_build_bonus_twice(self):
        v = colonies(view(), ("Titania", [], 1), ("Ceres", [], 1))
        v["preludeCardsInHand"] = [{"name": "Vital Colony"}]
        val = value.value_card("Vital Colony", value.Outlook(v))
        self.assertTrue(any("Titania: Gain 5, 3, or 2 VP ×2" in label for label, _ in val.parts), val.parts)
        self.assertGreaterEqual(val.value, 2 * 5 * value.VP - 10)

    def test_double_down_copies_the_other_prelude(self):
        v = view()
        v["preludeCardsInHand"] = [{"name": "Business Empire"}, {"name": "Double Down"}]
        ctx = value.Outlook(v)
        dd, be = value.value_card("Double Down", ctx), value.value_card("Business Empire", ctx)
        self.assertAlmostEqual(dd.value, be.value)
        self.assertGreater(dd.value, 0)
        p = plan.opening(game(), "Cheung Shing MARS", ["Business Empire", "Double Down"], (), gens=1)
        self.assertEqual(p.state.prod["megacredits"], 3 + 6 + 6)

    def test_aridor_gains_production_for_new_tag_types(self):
        p = plan.opening(game(), "Aridor", ["Business Empire", "Donation"], (), gens=1)
        self.assertEqual(p.state.prod["megacredits"], 6 + 1)  # Business Empire's Earth tag is a new type
        ctx = value.Outlook(view(generation=1, temperature=-30, oxygen=0, oceans=0))
        self.assertTrue(any(label.startswith("new tag types") and amt > 0
                            for label, amt in value.value_card("Aridor", ctx).combo))
        v = view(tags={"earth": 1})
        v["thisPlayer"]["tableau"] = [{"name": "Aridor"}]
        parts = value.value_card("Mine", value.Outlook(v)).parts
        self.assertTrue(any(label.startswith("your Aridor") for label, _ in parts), parts)

    def test_saturn_systems_counts_its_own_and_rivals_jovian_tags(self):
        ctx = value.Outlook(view(generation=1, temperature=-30, oxygen=0, oceans=0))
        combo = dict(value.value_card("Saturn Systems", ctx).combo)
        self.assertTrue(any(k.startswith("effect ×") and k.endswith("own)") for k in combo), combo)
        self.assertTrue(any(k.startswith("rivals' jovian tags") and a > 0 for k, a in combo.items()), combo)


class PreludeCash(unittest.TestCase):
    """4. Prelude M€ is spent in generation 1."""

    def test_donation_pays_for_16_psyche_in_generation_1(self):
        with_cash = plan.opening(game(), "Saturn Systems", ["UNMI Contractor", "Donation"], SATURN_KEEP)
        self.assertEqual(first_gen(with_cash, "16 Psyche"), 1)
        without = plan.opening(game(), "Saturn Systems", ["UNMI Contractor", "Mohole"], SATURN_KEEP)
        self.assertNotEqual(first_gen(without, "16 Psyche"), 1)


class KeptCards(unittest.TestCase):
    """5. Cards whose requirement is reached later are scheduled; cards worth less than they cost are not kept."""

    def test_later_requirement_is_scheduled(self):
        p = plan.opening(game(), "Cheung Shing MARS", [], ["Kelp Farming"])
        played = first_gen(p, "Kelp Farming")
        self.assertIsNotNone(played)
        oceans = {gen: plan._whole("oceans", par["oceans"]) for gen, par in p.state.trace}
        self.assertGreaterEqual(oceans[played], 6)

    def test_card_played_only_with_leftover_money_is_not_kept(self):
        # Neutralizer Factory needs Venus 10%: reached late, worth less than 7 + 3 M€ then.
        v = opening_view(["Cheung Shing MARS"], ["Donation", "Business Empire"], ["Neutralizer Factory", "Mine"])
        _, _, _, keep = plan.best_openings(v, top=1)[0]
        self.assertIn("Mine", keep)
        self.assertNotIn("Neutralizer Factory", keep)

    def test_value_prices_a_card_when_its_requirement_is_met(self):
        # Kelp Farming at 0 oceans pays production only from the generation 6 oceans are likely placed.
        ctx = value.Outlook(view(generation=1, temperature=-30, oxygen=0, oceans=0, venus=0))
        v = value.value_card("Kelp Farming", ctx)
        self.assertTrue(any(f.startswith("valued as played in generation") for f in v.flags), v.flags)
        self.assertTrue(any(f.startswith("NOT PLAYABLE YET: oceans 0") for f in v.flags), v.flags)
        self.assertLess(v.value, value.value_card("Kelp Farming", value.Outlook(view(oceans=6))).value)


class Compression(unittest.TestCase):
    """6. Projections separate openings: the economy compounds and the table finishes terraforming on schedule."""

    def test_table_finishes_terraforming_by_the_projected_end(self):
        p = plan.opening(game(), "Cheung Shing MARS", [], [])
        planner = plan._Planner(game())
        steps_left = sum((plan.MAX[k] - plan._whole(k, x)) / plan.STEP[k]
                         for k, x in p.state.trace[-1][1].items() if k != "venus")
        self.assertLessEqual(steps_left, planner.table_pace + 1)

    def test_drawn_cards_production_feeds_the_economy(self):
        p = plan.project(game(mc=40, generation=1), gens=6)
        self.assertGreater(p.state.prod["megacredits"], 0)

    def test_draft_picks_beat_random_cards(self):
        n = 100
        plain = plan._pick_weights(n, draft=False)
        drafted = plan._pick_weights(n, draft=True)
        for weights in plain + drafted:
            self.assertAlmostEqual(sum(weights), 1.0)
        rank = lambda w: sum(j * x for j, x in enumerate(w))  # expected position in the deck, 0 = best
        self.assertLess(rank(plain[0]), rank(plain[3]))
        self.assertLess(rank(drafted[1]), rank(plain[1]))

    def test_income_buys_more_drawn_cards(self):
        rich = plan.opening(game(), "Cheung Shing MARS", ["Business Empire"], ())
        poor = plan.opening(game(), "Cheung Shing MARS", [], ())
        self.assertGreater(sum(rich.state.stream.values()), sum(poor.state.stream.values()))
        self.assertGreater(rich.vp, poor.vp)


def rival_view(**rival):
    v = view(generation=8, temperature=0, oxygen=10, oceans=7)
    v["game"].update(milestones=[], spaces=[], gameOptions=dict(v["game"]["gameOptions"], boardName="tharsis"))
    for p in v["players"]:
        p.update(megacredits=0, steel=0, titanium=0, plants=0, heat=0, energyProduction=0, heatProduction=0,
                 plantProduction=0, megacreditProduction=0, steelProduction=0, titaniumProduction=0, cardsInHandNbr=0,
                 victoryPointsBreakdown={k: 0 for k in ("terraformRating", "milestones", "awards", "greenery", "city",
                                                         "victoryPoints", "total")})
    v["players"][1].update(rival)
    return v


class RivalProjection(unittest.TestCase):
    """7. `tfm vp` projects rivals to the end of the game."""

    def test_colony_vp_comes_from_the_log(self):
        logs = [{"message": "${0} gained ${1} VP", "data": [{"type": 2, "value": "green"}, {"type": 1, "value": "5"}]},
                {"message": "${0} gained ${1} VP", "data": [{"type": 2, "value": "green"}, {"type": 1, "value": "2"}]},
                {"message": "${0} traded with ${1}", "data": [{"type": 2, "value": "green"}]}]
        self.assertEqual(score.colony_vp_from_logs(logs), {"green": 7})
        v = rival_view()
        v["game"]["colonies"] = [{"name": "Titania", "colonies": ["green"], "trackPosition": 1}]
        parts, _ = score.estimate(v, v["players"][1], score.colony_vp_from_logs(logs))
        self.assertEqual(parts["victoryPoints"], 7)  # the build (5) and a trade (2), not the build alone

    def test_planetary_track_end_scores_most_tags(self):
        v = rival_view(tags={"venus": 4})
        v["game"]["pathfinders"] = {"venus": 17, "earth": 3}
        self.assertEqual(score.track_points(v["game"], v["players"][1], v["players"]), 2)
        self.assertEqual(score.track_points(v["game"], v["players"][0], v["players"]), 0)

    def test_rest_of_game_counts_hand_heat_plants_and_resources(self):
        rival = dict(megacredits=60, cardsInHandNbr=12, plants=9, plantProduction=0, heat=8, terraformRating=40,
                     tableau=[{"name": "Birds", "resources": 3}])
        v = rival_view(**rival)
        more, why = score.rest_of_game(v["players"][1], v["game"], 1, (1.6, 14))
        # 1 greenery (+1 oxygen TR), 1 heat TR, 4 hand cards (60 M€ / 14) at 1.6 VP, Birds +1 animal.
        self.assertEqual(more, round(2 + 1 + 4 * 1.6 + 1))
        self.assertIn("4 of 12 hand cards", why)
        lines = score.report(v, logs=[], gens_left=1, card_rate=(1.6, 14))
        self.assertTrue(any("p1: ~" in line and "by game end ~" in line for line in lines), lines)

    def test_two_generations_add_income(self):
        v = rival_view(megacredits=20, cardsInHandNbr=10, terraformRating=40, megacreditProduction=10)
        one, _ = score.rest_of_game(v["players"][1], v["game"], 1, (1.6, 14))
        two, _ = score.rest_of_game(v["players"][1], v["game"], 2, (1.6, 14))
        self.assertGreater(two, one)


class AwardHands(unittest.TestCase):
    """8. Award projections count rivals' hands and the generations left."""

    def outlook(self, hand, mc):
        a = award("A. Manufacturer", 8, 7, funded_by="p0")
        v = view(awards=[a])
        v["players"][1].update(cardsInHandNbr=hand, megacredits=mc)
        return value.award_outlook(a, value.Outlook(v, gens_left=1))

    def test_big_rival_hand_lowers_your_chance(self):
        none, rich, poor = self.outlook(0, 0), self.outlook(19, 80), self.outlook(19, 5)
        self.assertLess(rich["p1"], none["p1"] - 0.15)
        self.assertLess(rich["p1"], poor["p1"])  # a hand it cannot pay for counts less


def labels(v):
    return [label for label, _ in v.parts]


class CheaperStandardProject(unittest.TestCase):
    """9. A standard project is only compared with a card whose main effect is the same kind."""

    def test_energizer_power_plant_is_not_compared_with_cards_without_energy(self):
        ms = {"name": "Energizer", "scores": [{"color": "red", "score": 5}]}
        v = view(milestones=[ms])
        v["thisPlayer"]["energyProduction"] = 5
        ctx = value.Outlook(v)
        for name in ("Weather Balloons", "Carbon Nanosystems", "Atmoscoop"):
            with self.subTest(card=name):
                val = value.value_card(name, ctx)
                value.flag_cheaper_standard_projects([val], ctx)
                self.assertFalse(any(f.startswith("STANDARD PROJECT") for f in val.flags), val.flags)
        self.assertEqual(value.main_effect(value.value_card("Atmoscoop", ctx), ctx), "temperature")


class Atmoscoop(unittest.TestCase):
    """10. Atmoscoop's 2 temperature or 2 Venus steps are priced."""

    def test_two_steps(self):
        ctx = value.Outlook(view(temperature=-20))
        v = value.value_card("Atmoscoop", ctx)
        self.assertGreaterEqual(v.tr, 2)
        self.assertGreater(v.value, 2 * ctx.tr)


class ActionsWaitForRequirements(unittest.TestCase):
    """11. A card not playable yet acts only from the generation its requirement is likely met."""

    def test_livestock_at_two_percent_oxygen(self):
        ctx = value.Outlook(view(oxygen=2), gens_left=6)
        v = value.value_card("Livestock", ctx)
        uses = next(int(label.split("×")[1].split()[0]) for label in labels(v) if label.startswith("action ×"))
        self.assertLess(uses, 6)
        ready = value.value_card("Livestock", value.Outlook(view(oxygen=9), gens_left=6))
        self.assertTrue(any(label.startswith("action ×6") for label in labels(ready)), labels(ready))


class PlayConditions(unittest.TestCase):
    """12. Custom play conditions are flagged, in value and in draft/buy lists."""

    def option_ctx(self, v):
        return options.Context(v)

    def test_shipment_to_earth_needs_3_steel(self):
        v = view()
        v["thisPlayer"].update(plants=5, steel=1)
        flags = value.value_card("Shipment to Earth", value.Outlook(v), buying=True).flags
        self.assertIn("NOT PLAYABLE YET: needs 3 plants and 3 steel to lose (short: 3 steel)", flags)
        v["game"]["gameOptions"]["boardName"] = "tharsis"
        node = {"type": "card", "title": "Select a card to keep", "min": 1, "max": 1,
                "cards": [{"name": "Shipment to Earth"}, {"name": "Mine"}]}
        listed = [lf.label for lf in options.leaves(node, self.option_ctx(v))]
        self.assertIn("⚠ now: needs 3 plants and 3 steel", listed[0])
        self.assertNotIn("⚠", listed[1])

    def test_class_action_lawsuit_needs_one_leader_in_corruption(self):
        v = view()
        flags = value.value_card("Class-action Lawsuit", value.Outlook(v)).flags
        self.assertTrue(any(f.startswith("NOT PLAYABLE YET: needs one player with strictly the most corruption")
                            for f in flags), flags)
        v["players"][2]["underworldData"] = {"corruption": 3}
        self.assertIn("targets p2 (3 corruption)", value.value_card("Class-action Lawsuit", value.Outlook(v)).flags)


class Undervalued(unittest.TestCase):
    """13. Cards whose custom effects were missing."""

    def test_comet_aiming_places_an_ocean_every_other_generation(self):
        v = view()
        v["thisPlayer"]["titaniumProduction"] = 2
        val = value.value_card("Comet Aiming", value.Outlook(v, gens_left=5))
        self.assertTrue(any(label.startswith("action ×4") for label in labels(val)), labels(val))
        self.assertEqual(val.raises["oceans"], 2)  # fuel, ocean, fuel, ocean
        self.assertGreater(val.value, 0)

    def test_museum_of_early_colonisation_production(self):
        val = value.value_card("Museum of Early Colonisation", value.Outlook(view()))
        self.assertEqual({r: val.prod.get(r) for r in ("energy", "steel", "titanium", "plants")},
                         {"energy": -1, "steel": 1, "titanium": 1, "plants": 1})

    def test_excavator_leasing_counts_everyones_excavations(self):
        v = view(generation=5)
        v["game"]["gameOptions"]["expansions"]["underworld"] = True
        v["game"]["spaces"] = [{"id": str(i), "excavator": "green"} for i in range(8)]  # 2 per finished generation
        val = value.value_card("Excavator Leasing", value.Outlook(v, gens_left=4))
        self.assertTrue(any(label.startswith("1 M€ per excavation by anyone ×8.0") for label in labels(val)), labels(val))

    def test_helion_heat_is_worth_one_megacredit(self):
        v = view(temperature=6)
        ctx = value.Outlook(v, gens_left=3)
        self.assertLess(ctx.heat, 1)
        helion = value.value_card("Helion", ctx)
        self.assertIn(("+3 heat prod × 2", 6.0), helion.parts)
        v["thisPlayer"]["tableau"] = [{"name": "Helion"}]
        self.assertEqual(value.Outlook(v, gens_left=3).heat, 1.0)

    def test_card_text_without_renderer_glyphs(self):
        self.assertTrue(data.card_text("Ceres Tech Market").startswith("Action: Discard any number of cards"))
        self.assertEqual(data.card_text("Vital Colony"), "Place a colony. Receive the placement bonus twice.")

    def test_ceres_tech_market_action_is_priced(self):
        val = value.value_card("Ceres Tech Market", value.Outlook(view()))
        self.assertTrue(any(label.startswith("action ×") for label in labels(val)), labels(val))
        self.assertFalse(val.manual, val.manual)


class Overvalued(unittest.TestCase):
    """14. Trade fleets from the colonies in play; Boom Town's own titanium at 2 M€."""

    def test_trade_fleet_from_the_colonies_left(self):
        poor = colonies(view(), ("Titania", [], 5), ("Triton", [], 1))
        rich = colonies(view(), ("Luna", [], 4), ("Ceres", [], 4))
        for v in (poor, rich):
            v["thisPlayer"]["fleetSize"] = 1
        cheap = value.value_card("Space Port Colony", value.Outlook(poor))
        good = value.value_card("Sky Docks", value.Outlook(rich))
        fleet = lambda val: sum(a for label, a in val.parts if "trade fleet" in label)
        self.assertEqual(fleet(cheap), 0)  # Titania at 0 VP and 1 titanium don't cover the 9 M€ trade
        self.assertGreater(fleet(good), 0)

    def test_boom_town_titanium_at_two(self):
        val = value.value_card("Boom Town", value.Outlook(view(), gens_left=4))
        self.assertIn(("+2 titanium prod × 3", 2 * 2 * 3), val.parts)


def cli_view(waiting_for, **game):
    v = rival_view()
    v["game"].update(name="T", phase="action", gameAge=1, undoCount=0, colonies=[], passedPlayers=[], **game)
    for p in v["players"]:
        p.update(actionsThisGeneration=[], actionsTakenThisGame=0, fleetSize=1, tradesThisGeneration=0,
                 timer={"running": False, "sumElapsed": 0, "startedAt": 0}, energy=0)
    v["thisPlayer"] = v["players"][0]
    v["waitingFor"] = waiting_for
    return v


def run_cli(argv, v, seat=None):
    client = mock.Mock()
    client.player.return_value = v
    client.logs.return_value = []
    client.submit.return_value = v
    seat = seat if seat is not None else {"name": "x", "server": "s", "player_id": "p"}
    out = io.StringIO()
    with mock.patch.object(cli.seats, "load", return_value=seat), mock.patch.object(cli.seats, "save"), \
            mock.patch.object(cli, "_client", return_value=client), contextlib.redirect_stdout(out):
        cli.main(argv)
    return out.getvalue(), seat


MENU = {"type": "or", "title": "Take your first action", "options": [
    {"type": "option", "title": "Convert 8 heat into temperature"}, {"type": "option", "title": "Pass for this generation"}]}


class Cli(unittest.TestCase):
    """15-20. CLI and option listing."""

    def test_card_shows_colony_tiles(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["card", "Titania", "europa"])
        self.assertIn("Titania [colony tile] — build: Gain 5, 3, or 2 VP; trade: Gain n VP", out.getvalue())
        self.assertIn("Europa [colony tile] — build: Place an ocean tile", out.getvalue())

    def test_colony_build_prompt_shows_the_build_bonus(self):
        v = cli_view(None)
        node = {"type": "colony", "title": "Select where to build a colony",
                "coloniesModel": [{"name": "Titania", "colonies": [], "trackPosition": 1}]}
        label = options.leaves(node, options.Context(v))[0].label
        self.assertIn("build: Gain 5, 3, or 2 VP", label)
        node["title"] = "Select colony to trade with"
        self.assertNotIn("build:", options.leaves(node, options.Context(v))[0].label)

    def test_heat_conversion_after_temperature_is_maxed(self):
        v = cli_view(MENU, temperature=8)
        labels_ = [lf.label for lf in options.leaves(MENU, options.Context(v))]
        self.assertIn("temperature maxed: no TR", labels_[0])
        v = cli_view(MENU, temperature=0)
        self.assertNotIn("maxed", options.leaves(MENU, options.Context(v))[0].label)

    def test_turn_prints_each_block_once(self):
        text, _ = run_cli(["turn"], cli_view(MENU))
        self.assertEqual(text.count("YOUR DECISION"), 1)
        self.assertEqual(sum(1 for line in text.splitlines() if line.startswith("YOU:")), 1)
        self.assertEqual(text.count("[1] Convert 8 heat"), 1)

    def test_underground_tokens_are_explained(self):
        v = cli_view(None)
        v["game"]["spaces"] = [{"id": "11", "spaceType": "land", "undergroundResource": "plant2pertemp"}]
        self.assertIn("this generation: +2 plants each time anyone raises the temperature",
                      options.describe_space("11", options.Context(v)))
        node = {"type": "claimedUndergroundToken", "title": "Claim", "min": 1, "max": 1,
                "tokens": ["microbe2pertemp", "place6mc"]}
        hint = options.needs(node, options.Context(v))
        self.assertIn("0:microbe2pertemp (this generation: +2 microbes", hint)
        self.assertIn("nothing when excavated", hint)

    def test_hazard_space_bonus_is_not_paid(self):
        v = cli_view(None)
        v["game"]["spaces"] = [{"id": "11", "spaceType": "land", "bonus": [1], "tileType": 24}]
        text = options.describe_space("11", options.Context(v))
        self.assertIn("(NOT paid: the tile covers a hazard)", text)
        v["game"]["spaces"] = [{"id": "11", "spaceType": "land", "bonus": [1]}]
        self.assertNotIn("NOT paid", options.describe_space("11", options.Context(v)))

    def test_play_without_expect_on_a_menu_prints_a_reminder(self):
        v = cli_view(MENU)
        _, seat = run_cli(["options"], v)
        text, seat = run_cli(["play", "2"], v, seat)
        self.assertIn("tip: add --expect TEXT", text)
        _, seat = run_cli(["options"], v, seat)
        text, _ = run_cli(["play", "2", "--expect", "Pass"], v, seat)
        self.assertNotIn("tip:", text)


class CurrentGeneration(unittest.TestCase):
    """21. The plan spends this generation's M€ (the app's player model calls it `megacredits`)."""

    def test_current_generation_is_spent(self):
        v = game(["Mine"], mc=39, generation=7, temperature=-10, oxygen=8, oceans=6, heat=11)
        self.assertEqual(plan._Planner(v, 2).state_from_view().stock["megacredits"], 39)
        p = plan.project(v, gens=2)
        self.assertEqual(first_gen(p, "Mine"), 7)
        self.assertIn((7, "temperature (heat)"), p.plays)


if __name__ == "__main__":
    unittest.main()
