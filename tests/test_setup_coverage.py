"""Corporations and preludes: every custom-code effect is priced or listed as deliberately not modelled, and the
shared models (extra preludes, colonies, trades, cards played from hand, triggers) price and simulate as the card
text says. Run: python3 -m unittest discover tests"""
import contextlib
import io
import re
import unittest

from tfm import cli, data, plan, value
from test_live34 import colonies, opening_view
from test_plan import game
from test_value import view

SETUP = ("corporation", "prelude")


def has_custom_code(name):
    """True when the app runs part of the card in custom code (bespokePlay, bespokeAction, triggers), or its text
    has an effect the exported behavior does not carry: a first action with no firstAction, an "Effect:" with no
    discount or titanium value, a wild tag or a changed rule ("instead of")."""
    beh = data.behavior(name) or {}
    text = data.card_text(name)
    if beh.get("bespokePlay") or beh.get("bespokeAction") or beh.get("triggers"):
        return True
    if re.search(r"first action", text, re.I) and not beh.get("firstAction"):
        return True
    if re.search(r"\beffect\b", text, re.I) and not beh.get("cardDiscount") and \
            not (beh.get("behavior") or {}).get("titaniumValue"):
        return True
    return bool(re.search(r"wild tag|instead of", text, re.I))


def modelled(name):
    return name in value.CUSTOM_BEHAVIORS or name in value.OWN_TRIGGERS or name in value.RIVAL_TRIGGERS or \
        name in value.PRICED_EFFECTS


def custom_setup_cards():
    return [n for n, c in data.cards().items() if c.get("type") in SETUP and has_custom_code(n)]


def opening_ctx():
    return value.Outlook(view(generation=1, temperature=-30, oxygen=0, oceans=0, venus=0), gens_left=8)


def with_colonies(v, *names, players_colonies=()):
    colonies(v, *((n, list(players_colonies), 1) for n in names))
    v["game"]["gameOptions"]["expansions"].update(colonies=True)
    return v


class Coverage(unittest.TestCase):
    def test_every_custom_corporation_and_prelude_is_modelled_or_explained(self):
        missing = [n for n in custom_setup_cards() if not modelled(n) and n not in value.NOT_MODELLED]
        self.assertEqual(missing, [], "add a model (value.SETUP_BEHAVIORS / OWN_TRIGGERS) or a NOT_MODELLED reason")

    def test_not_modelled_entries_have_a_reason_and_no_model(self):
        for name, reason in value.NOT_MODELLED.items():
            self.assertIn(name, data.cards(), name)
            self.assertTrue(reason and len(reason) > 20, name)
            self.assertFalse(modelled(name), f"{name} is modelled and listed as not modelled")

    def test_modelled_cards_no_longer_ask_you_to_read_the_card(self):
        ctx = opening_ctx()
        for name in custom_setup_cards():
            if not modelled(name):
                continue
            notes = [m for m in value.value_card(name, ctx).manual if "custom code" in m or "ongoing effect" in m]
            self.assertEqual(notes, [], name)

    def test_coverage_counts(self):
        cards = custom_setup_cards()
        covered = sum(1 for n in cards if modelled(n))
        self.assertGreaterEqual(covered, 120)
        self.assertEqual(covered + sum(1 for n in cards if n in value.NOT_MODELLED and not modelled(n)), len(cards))


class ExtraSetupCards(unittest.TestCase):
    def test_best_of_k_is_the_order_statistic(self):
        self.assertAlmostEqual(value.best_of([0, 10], 1), 5)
        self.assertAlmostEqual(value.best_of([0, 10], 2), 7.5)
        self.assertAlmostEqual(value.best_of([0, 10], 1, cost=6, optional=True), 2)

    def test_valley_trust_and_new_partner_price_the_extra_prelude(self):
        ctx = opening_ctx()
        pool = value.setup_pool(ctx, "prelude")
        mean = sum(pool) / len(pool)
        vt = value.value_card("Valley Trust", ctx)
        np_ = value.value_card("New Partner", ctx)
        self.assertGreater(vt.value, 37 + mean)
        self.assertGreater(np_.value, ctx.phases + mean)
        self.assertGreater(vt.value - 37, np_.value - ctx.phases)  # best of 3 beats best of 2

    def test_board_of_directors_only_plays_preludes_worth_12(self):
        ctx = opening_ctx()
        v = value.value_card("Board of Directors", ctx)
        self.assertTrue(any(label.startswith("action ×4") for label, _ in v.parts), v.parts)


class ColonyModels(unittest.TestCase):
    def test_colonies_are_priced_from_the_tiles_in_play(self):
        v = with_colonies(opening_view(), "Ceres", "Titania", "Europa", "Luna", "Pluto")
        ctx = value.Outlook(v)
        builds = {name: worth for worth, _, name in value.colony_builds(ctx)}
        self.assertEqual(set(builds), {"Ceres", "Titania", "Europa", "Luna", "Pluto"})
        self.assertEqual(len({round(w) for w in builds.values()}), 5)
        # Titania: 5 VP, less the owner's 3 M€ on each of the frequent trades there.
        rates = value.tile_trade_rates(ctx)
        self.assertAlmostEqual(builds["Titania"], 5 * value.VP - 3 * rates["Titania"] * ctx.gens_left)
        self.assertEqual(max(rates, key=rates.get), "Titania")  # 2 VP a trade: the best trade at the start
        flags = value.value_card("Free Trade Port", ctx).flags
        self.assertTrue(any(f.startswith("colony tiles compared: Ceres") for f in flags), flags)

    def test_trade_advance_trades_with_every_colony(self):
        v = with_colonies(opening_view(), "Ceres", "Titania", "Luna")
        ctx = value.Outlook(v)
        expected = sum(value.trade_value(c, ctx, 1) for c in value._colony_models(ctx)) + 2
        self.assertAlmostEqual(value.value_card("Trade Advance", ctx).value, expected)
        self.assertGreater(expected, 20)

    def test_early_colonization_moves_every_track(self):
        v = with_colonies(opening_view(), "Luna", "Ceres")
        ctx = value.Outlook(v)
        parts = dict(value.value_card("Early Colonization", ctx).parts)
        track = next(a for label, a in parts.items() if label.startswith("colony tracks +2"))
        luna = value._colony_models(ctx)[0]
        self.assertAlmostEqual(track, value.trade_value(luna, ctx, 2) - value.trade_value(luna, ctx))

    def test_huygens_trades_free(self):
        v = with_colonies(opening_view(), "Luna", "Ceres")
        ctx = value.Outlook(v)
        parts = dict(value.value_card("Huygens Observatory", ctx).parts)
        self.assertAlmostEqual(parts["a free trade"], value.free_trade_value(ctx))


class Triggers(unittest.TestCase):
    def test_rival_triggers_count_shared_parameters(self):
        ctx = opening_ctx()
        self.assertAlmostEqual(value.rival_matches(ctx, "ocean"), 9 * 3 / 4)
        polaris = value.value_card("Polaris", ctx)
        self.assertTrue(any(label.startswith("rivals' oceans") and a > 10 for label, a in polaris.combo), polaris.combo)

    def test_splice_pays_for_its_own_and_rivals_microbe_tags(self):
        v = value.value_card("Splice", opening_ctx())
        labels = [label for label, _ in v.combo]
        self.assertTrue(any("incl. 1 own" in label for label in labels), labels)
        self.assertTrue(any(label.startswith("rivals' microbe tags") for label in labels), labels)

    def test_prelude_tags_fire_corporation_triggers(self):
        v = view(generation=1, temperature=-30, oxygen=0, oceans=0, venus=0)
        v["thisPlayer"]["tableau"] = [{"name": "Point Luna"}]
        val = value.value_card("Trade Advance", value.Outlook(v))  # an Earth-tag prelude
        self.assertTrue(any(label.startswith("your Point Luna") for label, _ in val.parts), val.parts)


class Simulation(unittest.TestCase):
    def start(self, v, *names):
        """A planner and generation-1 state after playing `names` (a corporation and preludes) as plan.opening does."""
        planner = plan._Planner(v, 3)
        s = plan._State()
        s.params = {"temperature": -30.0, "oxygen": 0.0, "oceans": 0.0, "venus": 0.0}
        for name in names:
            ctx = planner.ctx(s, 0)
            _, residual = planner.valuation(name, s, 0, ctx)
            planner.apply(name, s, ctx, residual)
            if name in plan.PLAY_FROM_HAND:
                planner.play_from_hand(name, s, 0)
        return planner, s

    def test_manutech_gains_the_resources_of_each_production_step_once(self):
        planner, s = self.start(game(), "Manutech", "Business Empire")
        self.assertEqual(s.stock["steel"], 1)  # its own steel production, "including this"
        self.assertEqual(s.stock["megacredits"], 35 + 6 - 6)
        self.assertEqual(s.prod["megacredits"], 6)
        # value.py's price of that gain is not banked on top.
        ctx = planner.ctx(s, 0)
        v = value.value_card("Business Empire", ctx)
        self.assertTrue(any(label.startswith("your Manutech") for label, _ in v.parts), v.parts)
        self.assertAlmostEqual(planner.valuation("Business Empire", s, 0, ctx)[1], 0.0)

    def test_ecoline_makes_greeneries_from_7_plants(self):
        planner, s = self.start(game(), "Ecoline")
        s.stock["plants"] = 7
        planner.convert(s, 1)
        self.assertEqual(s.greeneries, 1)
        fresh = self.start(game())[1]
        self.assertAlmostEqual(planner.valuation("Ecoline", fresh, 0, planner.ctx(fresh, 0))[1], 0.0)

    def test_card_buy_cost_follows_the_corporation(self):
        for corp, cost in (("Polyphemos", 5), ("TerraLabs Research", 1), ("Teractor", value.BUY_COST)):
            planner, s = self.start(game(), corp)
            self.assertEqual(planner.buy_cost(s), cost, corp)

    def test_eccentric_sponsor_plays_a_kept_card_25_cheaper(self):
        v = game()
        p = plan.opening(v, "Teractor", ["Eccentric Sponsor"], ["Space Elevator", "Mine"], gens=3)
        self.assertIn((1, "Space Elevator (via Eccentric Sponsor)"), p.plays)
        planner, s = self.start(v, "Teractor")
        s.hand = ["Space Elevator"]
        self.assertAlmostEqual(planner.valuation("Eccentric Sponsor", s, 0, planner.ctx(s, 0))[1], 0.0)

    def test_trade_advance_separates_from_valuable_gases(self):
        v = with_colonies(opening_view(), "Ceres", "Titania", "Europa", "Luna", "Pluto")
        ta = plan.opening(v, "Teractor", ["Trade Advance", "Metals Company"], [])
        vg = plan.opening(v, "Teractor", ["Valuable Gases", "Metals Company"], [])
        self.assertGreater(ta.vp, vg.vp + 3)


class OpeningOutput(unittest.TestCase):
    def view(self):
        v = opening_view(["Teractor", "Vitor"], ["Trade Advance", "Valuable Gases", "Metals Company"], ["Mine"])
        return with_colonies(v, "Ceres", "Luna")

    def test_top_three_and_the_spread(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._print_plan(self.view(), [], opening=True)
        text = out.getvalue()
        self.assertIn("  3. ~", text)
        self.assertNotIn("  4. ~", text)
        self.assertRegex(text, r"spread: ~\d+ best to ~\d+ worst over 6 bundles \(worst: ")

    def test_named_bundle_shows_its_rank(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._print_plan(self.view(), ["Vitor", "Valuable Gases", "Metals Company"], opening=True)
        self.assertRegex(out.getvalue(), r"(rank \d of 6|below all 6) offered bundles .* spread ~\d+ best to ~\d+ worst")


if __name__ == "__main__":
    unittest.main()
