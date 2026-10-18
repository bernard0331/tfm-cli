"""Checks for tfm plan against small hand-built game views. Run: python3 -m unittest discover tests"""
import contextlib
import io
import time
import unittest
from unittest import mock

from tfm import cli, plan, value
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
        # spends at most 3 M€, so the two weak buys (7 + 7) must wait.
        v = game(["Soletta", "Peroxide Power", "SF Memorial"], mc=18)
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

    def test_future_matches_hook_drives_discounts_on_future_cards(self):
        v = game(mc=0)
        v["thisPlayer"]["tableau"] = [{"name": "Earth Office"}]
        flat = plan.project(v, gens=6).vp
        with mock.patch.object(value, "future_matches", create=True, new=lambda ctx, event: 0.0):
            none = plan.project(v, gens=6).vp
        with mock.patch.object(value, "future_matches", create=True,
                               new=lambda ctx, event: 2.0 * ctx.gens_left if event == "tag:earth" else 0.0):
            many = plan.project(v, gens=6).vp
        self.assertLess(none, flat)
        self.assertGreater(many, flat)

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
        self.assertNotIn("Biosphere Support", pres)
        self.assertIn("Business Network", keep)
        self.assertNotIn("Trans-Neptune Probe", keep)
        order = [(c, set(ps)) for _, c, ps, _ in ranked]
        self.assertLess(order.index((STRONG[0], set(STRONG[1]))), order.index((WEAK[0], set(WEAK[1]))))

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


if __name__ == "__main__":
    unittest.main()
