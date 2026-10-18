"""Checks for tfm plan against small hand-built game views. Run: python3 -m unittest discover tests"""
import contextlib
import io
import time
import unittest
from unittest import mock

from tfm import cli, deck, plan, value
from test_value import view


def game(hand=(), mc=0, generation=1, temperature=-30, oxygen=0, oceans=0, venus=0, **me):
    v = view(generation=generation, temperature=temperature, oxygen=oxygen, oceans=oceans, venus=venus,
             hand=[{"name": n} for n in hand])
    v["thisPlayer"].update(megaCredits=mc, terraformRating=20, citiesCount=0, **me)
    return v


def first_gen(p, name):
    return next((gen for gen, label in p.plays if label == name), None)


class PlayOrder(unittest.TestCase):
    def test_production_before_vp_early(self):
        # 4 M€ buys one of them in generation 1: the production card goes first, the VP card after.
        p = plan.project(game(["Dust Seals", "Mine"], mc=4), gens=8)
        self.assertEqual(first_gen(p, "Mine"), 1)
        self.assertGreater(first_gen(p, "Dust Seals"), 1)

    def test_vp_before_production_in_the_last_generation(self):
        # With no production phase left, production is worth nothing and only the VP card is played.
        p = plan.project(game(["Dust Seals", "Mine"], mc=4), gens=1)
        self.assertEqual(first_gen(p, "Dust Seals"), 1)
        self.assertIsNone(first_gen(p, "Mine"))

    def test_requirement_card_waits_for_the_parameter(self):
        # Lichen needs -24 °C; rivals warm Mars from -30 °C at the table pace.
        p = plan.project(game(["Lichen"], mc=60), gens=8)
        played = first_gen(p, "Lichen")
        self.assertIsNotNone(played)
        self.assertGreater(played, 1)
        temps = {gen: plan._whole("temperature", params["temperature"]) for gen, params in p.state.trace}
        self.assertGreaterEqual(temps[played], -24)
        self.assertLess(temps[played - 1], -24)

    def test_requirement_from_own_tags(self):
        # Gene Repair needs 3 science tags: Research gives 2, so it waits for Inventors' Guild's third.
        p = plan.project(game(["Gene Repair", "Research"], mc=60), gens=8)
        self.assertIsNone(first_gen(p, "Gene Repair"))
        p = plan.project(game(["Gene Repair", "Research", "Inventors' Guild"], mc=60), gens=8)
        self.assertGreaterEqual(first_gen(p, "Gene Repair"), first_gen(p, "Inventors' Guild"))

    def test_saving_for_an_expensive_card_beats_two_weak_buys(self):
        # 18 M€ now and 20 M€ income: Soletta (35) is affordable next generation only if this generation
        # spends at most 3 M€, so the two weak buys (7 + 7) must wait. Drawn cards are left out: this checks
        # the lookahead, not whether drawn cards beat Soletta.
        v = game(["Soletta", "Peroxide Power", "SF Memorial"], mc=18)
        with mock.patch.object(plan._Planner, "stream_options", return_value=[]):
            saved = plan.project(v, gens=8)
            planner = plan._Planner(v, 8)
            greedy = planner.run(planner.state_from_view(), branch=False)
        self.assertEqual(first_gen(saved, "Soletta"), 2)
        self.assertNotIn(first_gen(saved, "Peroxide Power"), (1,))
        self.assertEqual(first_gen(greedy, "Peroxide Power"), 1)
        self.assertTrue(first_gen(greedy, "Soletta") is None or first_gen(greedy, "Soletta") > 2)
        self.assertGreater(saved.vp, greedy.vp)


class Projection(unittest.TestCase):
    def test_leftover_money_is_spent_in_the_last_generation(self):
        p = plan.project(game(mc=40), gens=1)
        self.assertTrue(any(label.startswith("SP ") for _, label in p.plays))

    def test_plants_and_heat_convert(self):
        p = plan.project(game(mc=0, plants=8, heat=8), gens=1)
        labels = [label for _, label in p.plays]
        self.assertIn("greenery (plants)", labels)
        self.assertIn("temperature (heat)", labels)
        self.assertEqual(p.parts["greeneries"], 1)
        self.assertEqual(p.parts["TR gained"], 2)  # oxygen from the greenery and temperature from heat

    def test_decision_value_is_with_minus_without(self):
        v = game(["Mine"], mc=10)
        delta = plan.decision_value(v, "Mine")
        self.assertAlmostEqual(delta, plan.project(v).vp - plan.project(v, without=["Mine"]).vp)
        self.assertGreater(delta, 0)
        self.assertGreater(plan.decision_value(v, "Business Network", buying=True), 0)

    def test_discount_lowers_hand_costs(self):
        planner = plan._Planner(game(), 8)
        s = planner.state_from_view()
        before = planner.card_cost("Business Network", s)[0]
        s.tableau.append({"name": "Earth Office"})
        self.assertEqual(planner.card_cost("Business Network", s)[0], before - 3)

    def test_deck_rate_drives_discounts_on_future_cards(self):
        v = game(mc=0)
        v["thisPlayer"]["tableau"] = [{"name": "Earth Office"}]
        flat = plan.project(v, gens=6).vp
        with mock.patch.object(deck, "matches_per_gen", new=lambda ctx, event: 0.0):
            none = plan.project(v, gens=6).vp
        with mock.patch.object(deck, "matches_per_gen",
                               new=lambda ctx, event: 2.0 if event == "tag:earth" else 0.0):
            many = plan.project(v, gens=6).vp
        self.assertLess(none, flat)
        self.assertGreater(many, flat)

    def test_future_draw_discount_is_not_banked_twice(self):
        # value.py prices Earth Office's discount on future draws; the simulation applies that discount to the
        # card stream itself, so it must not also be banked as a lump sum.
        planner = plan._Planner(game(), 6)
        s = planner.state_from_view()
        ctx = planner.ctx(s, 0)
        v = value.value_card("Earth Office", ctx)
        future = sum(a for label, a in v.combo if label.startswith("discount "))
        self.assertGreater(future, 0)
        self.assertLessEqual(planner.valuation("Earth Office", s, 0, ctx)[1], v.value - future + 1e-9)

    def test_fast_enough(self):
        hand = ["Kelp Farming", "Mine", "Earth Office", "Birds", "Strip Mine", "Comet", "Lichen", "Dust Seals",
                "Io Mining Industries", "Fish"]
        v = game(hand, mc=30, generation=3, temperature=-24, oxygen=2, oceans=2,
                 megacreditProduction=5, steelProduction=1, energyProduction=2, plantProduction=1)
        plan.project(v)  # warm the data caches
        start = time.perf_counter()
        plan.project(v)
        self.assertLess(time.perf_counter() - start, 0.25)  # target < 50 ms; generous for slow CI


STRONG = ("Cheung Shing MARS", ("Business Empire", "Allied Bank"), ("Micro-Mills", "Mine", "Business Network"))
WEAK = ("PhoboLog", ("Biosphere Support", "Loan"), ("Trans-Neptune Probe", "Dirigibles", "Medical Lab"))


class Opening(unittest.TestCase):
    def test_strong_opening_scores_above_weak(self):
        v = game()
        strong = plan.opening(v, *STRONG)
        weak = plan.opening(v, *WEAK)
        self.assertGreater(strong.vp, weak.vp + 3)

    def test_best_openings_ranks_offered_bundles(self):
        v = game()
        v["dealtCorporationCards"] = [{"name": STRONG[0]}, {"name": WEAK[0]}]
        v["dealtPreludeCards"] = [{"name": n} for n in STRONG[1] + WEAK[1]]
        v["dealtProjectCards"] = [{"name": n} for n in STRONG[2] + WEAK[2]]
        ranked = plan.best_openings(v, top=None)
        self.assertEqual(len(ranked), 2 * 6)  # each corporation with each pair of the 4 preludes
        p, corp, pres, keep = ranked[0]
        self.assertEqual(corp, STRONG[0])
        self.assertIn("Business Network", keep)
        order = [(c, set(ps)) for _, c, ps, _ in ranked]
        self.assertLess(order.index((STRONG[0], set(STRONG[1]))), order.index((WEAK[0], set(WEAK[1]))))
        self.assertEqual(order[-1], (WEAK[0], set(WEAK[1])))

    def test_cli_opening_bundle(self):
        v = game()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._print_plan(v, list((STRONG[0],) + STRONG[1] + STRONG[2]), opening=True)
        self.assertTrue(out.getvalue().startswith(f"OPENING {STRONG[0]} + Business Empire, Allied Bank · keep 3: ~"))

    def test_cli_plan_is_compact(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._print_plan(game(["Mine", "Dust Seals"], mc=10), ["Mine"])
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[0].startswith("PLAN: ~"))
        self.assertLessEqual(len(lines), 12)
        self.assertTrue(lines[-1].startswith("  Mine: "))



class LiveGameFixes(unittest.TestCase):
    """`tfm plan` estimates two agent seats found wrong in a live 3-player game (g506b18d8ce00)."""

    def test_opening_respects_production_to_give_up(self):
        # Noctis City gives up 1 energy production: not playable in generation 1 without any.
        p = plan.opening(game(), "Cheung Shing MARS", (), ["Noctis City"])
        self.assertNotEqual(first_gen(p, "Noctis City"), 1)
        # Industrial Complex raises every production below 1 to 1, energy included.
        p = plan.opening(game(), "Cheung Shing MARS", ["Industrial Complex"], ["Noctis City"])
        self.assertEqual(first_gen(p, "Noctis City"), 1)
        self.assertEqual(p.state.prod["energy"], 0)  # Noctis City gave up the energy Industrial Complex added
        self.assertTrue(all(p.state.prod[r] >= 1 for r in ("steel", "titanium", "plants", "heat")), p.state.prod)

    def test_opening_respects_underground_token_requirement(self):
        # Geothermal Network needs 3 underground tokens; Hadesphere's action digs one per generation.
        p = plan.opening(game(), "Hadesphere", (), ["Geothermal Network"])
        self.assertGreaterEqual(first_gen(p, "Geothermal Network"), 4)
        p = plan.opening(game(), "Cheung Shing MARS", (), ["Geothermal Network"])
        self.assertIsNone(first_gen(p, "Geothermal Network"))

    def test_opening_banks_preservation_program_penalty(self):
        # The skipped TR is banked at value.py's price (it assumes you gain TR every generation), on top of the
        # 5 TR the simulation applies.
        planner = plan._Planner(game(), 8)
        s = planner.state_from_view()
        _, residual = planner.valuation("Preservation Program", s, 0, planner.ctx(s, 0))
        self.assertAlmostEqual(residual, -(8 * VP_ + 8 * 7 / 2))
        tr = s.tr
        planner.apply("Preservation Program", s, planner.ctx(s, 0), residual)
        self.assertEqual(s.tr, tr + 5)

    def test_opening_starts_pharmacy_union_with_its_diseases_paid(self):
        planner = plan._Planner(game(), 8)
        s = plan._State()
        s.params = {"temperature": -30.0, "oxygen": 0.0, "oceans": 0.0, "venus": 0.0}
        ctx = planner.ctx(s, 0)
        planner.apply("Pharmacy Union", s, ctx, planner.valuation("Pharmacy Union", s, 0, ctx)[1])
        self.assertEqual(s.stock["megacredits"], 54 - 8)

    def test_prelude_megacredits_count_once(self):
        planner = plan._Planner(game(), 8)
        s = plan._State()
        s.params = {"temperature": -30.0, "oxygen": 0.0, "oceans": 0.0, "venus": 0.0}
        ctx = planner.ctx(s, 0)
        total, residual = planner.valuation("Donation", s, 0, ctx)
        planner.apply("Donation", s, ctx, residual)
        self.assertEqual(s.stock["megacredits"], 21)
        self.assertAlmostEqual(residual, 0)

    def test_drawn_cards_are_worth_less_near_the_end(self):
        planner = plan._Planner(game(), 8)
        top = [worth / (cost + value.BUY_COST) for worth, cost in (planner.stream_profile(i)[0] for i in range(8))]
        self.assertEqual(top, sorted(top, reverse=True))
        self.assertLess(top[-1], 1.0)  # in the last generation even the best drawn card returns less than it costs
        self.assertGreater(top[0], 1.0)

    def test_tr_card_is_played_now_with_three_generations_left(self):
        v = game(["Shipment to Earth"], mc=49, generation=6, temperature=-6, oxygen=8, oceans=6, plants=4, steel=3,
                 megacreditProduction=10)
        v["thisPlayer"]["terraformRating"] = 32
        p = plan.project(v, gens=3)
        self.assertEqual(first_gen(p, "Shipment to Earth"), 6)
        self.assertLess(p.parts["average cards"], 20)
        # Without the 3 plants and 3 steel it loses, it cannot be played at all.
        v["thisPlayer"].update(plants=0, steel=0, plantProduction=0, steelProduction=0)
        self.assertIsNone(first_gen(plan.project(v, gens=3), "Shipment to Earth"))

    def test_kept_cards_are_played_when_affordable(self):
        # Pharmacy Union's seat kept these and its generation-1 plans never played them: Small Open Pit Mine was
        # priced 0 (custom code) and Lava Tube Settlement needs energy production to give up.
        keep = ["Small Open Pit Mine", "Lava Tube Settlement", "Rover Construction"]
        p = plan.opening(game(), "Pharmacy Union", ["Industrial Complex", "Supply Drop"], keep)
        self.assertEqual([first_gen(p, n) for n in keep], [1, 1, 1])

    def test_industrial_complex_is_played_after_other_preludes(self):
        # Loan drops M€ production to -2; Industrial Complex then raises it to 1.
        p = plan.opening(game(), "Hadesphere", ["Industrial Complex", "Loan"], ())
        self.assertGreaterEqual(p.state.prod["megacredits"], 1)

    def test_live_plant_production_is_read(self):
        planner = plan._Planner(game(plantProduction=2), 8)
        self.assertEqual(planner.state_from_view().prod["plants"], 2)


VP_ = value.VP



class PlayOutput(unittest.TestCase):
    def test_play_refetches_a_response_without_choices(self):
        v = game()
        v["game"].update(phase="action", gameOptions=dict(v["game"]["gameOptions"], boardName="tharsis"))
        empty = dict(v, waitingFor={"type": "card", "title": "Select a card", "min": 1, "max": 1,
                                    "cards": [{"name": "Mine", "isDisabled": True}]})
        fresh = dict(v, waitingFor={"type": "or", "title": "Take an action", "options": [
            {"type": "option", "title": "Pass"}]})
        client = mock.Mock()
        client.player.return_value = fresh
        ctx = cli.options.Context(v)
        self.assertIs(cli._settled_view(client, empty, ctx), fresh)
        self.assertIs(cli._settled_view(client, dict(v, waitingFor=None), ctx), fresh)
        self.assertIs(cli._settled_view(client, fresh, ctx), fresh)
        self.assertEqual(client.player.call_count, 2)
        # A decision whose choices are all filtered out still lists the input itself.
        leaves = cli.options.leaves(empty["waitingFor"], ctx)
        self.assertEqual([lf.id for lf in leaves], ["1"])


if __name__ == "__main__":
    unittest.main()
