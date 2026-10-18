"""Checks for tfm vp (score.py) against small hand-built game views. Run: python3 -m unittest discover tests"""
import unittest

from tfm import score


def award(scores, funded=True):
    return {"name": "A", "playerName": "x" if funded else None,
            "scores": [{"color": c, "score": s} for c, s in scores.items()]}


class Awards(unittest.TestCase):
    def test_first_and_second(self):
        g = {"awards": [award({"red": 5, "green": 3, "blue": 1})]}
        self.assertEqual([score.award_points(g, c) for c in ("red", "green", "blue")], [5, 2, 0])

    def test_tie_for_first_shares_five_and_no_second(self):
        g = {"awards": [award({"red": 5, "green": 5, "blue": 4})]}
        self.assertEqual([score.award_points(g, c) for c in ("red", "green", "blue")], [5, 5, 0])

    def test_tie_for_second_shares_two(self):
        g = {"awards": [award({"red": 6, "green": 4, "blue": 4})]}
        self.assertEqual([score.award_points(g, c) for c in ("red", "green", "blue")], [5, 2, 2])

    def test_no_second_place_with_two_players(self):
        g = {"awards": [award({"red": 6, "green": 4})]}
        self.assertEqual([score.award_points(g, c) for c in ("red", "green")], [5, 0])

    def test_unfunded_awards_score_nothing(self):
        g = {"awards": [award({"red": 6, "green": 4, "blue": 1}, funded=False)]}
        self.assertEqual(score.award_points(g, "red"), 0)


class Cards(unittest.TestCase):
    def test_city_vp_includes_off_mars_cities(self):
        game = {"spaces": [
            {"id": "a", "tileType": 2, "spaceType": "land"},
            {"id": "b", "tileType": 3, "spaceType": "land"},
            {"id": "c", "tileType": 2, "spaceType": "colony"},
            {"id": "d", "tileType": 0, "spaceType": "land"},
        ], "colonies": []}
        for name in ("Immigration Shuttles", "Off-World City Living"):
            with self.subTest(card=name):
                player = {"color": "red", "tags": {}, "tableau": [{"name": name}]}
                self.assertEqual(score.card_points(player, game), (1, [], 0))

    def test_resource_and_tag_vp(self):
        player = {"color": "red", "tags": {"jovian": 3},
                  "tableau": [{"name": "Birds", "resources": 3}, {"name": "Io Mining Industries"}]}
        points, unknown, _ = score.card_points(player, {"spaces": [], "colonies": []})
        self.assertEqual((points, unknown), (3 + 3, []))



class FinalGeneration(unittest.TestCase):
    def test_upside_from_plants_heat_and_megacredits(self):
        game = {"temperature": 0, "oxygenLevel": 13, "oceans": 9}
        player = {"plants": 7, "plantProduction": 2, "heat": 16, "megaCredits": 30}
        # 1 greenery (+1 oxygen TR), 2 temperature steps, and 30 M€ = 2 asteroids at 14 M€ per TR.
        self.assertEqual(score.final_gen_upside(player, game)[0], 2 + 2 + 2)
        game = {"temperature": 8, "oxygenLevel": 14, "oceans": 9}
        # Everything maxed: greeneries score 1 VP each, M€ buys greeneries at 23 M€ per VP, heat is dead.
        self.assertEqual(score.final_gen_upside(player, game)[0], 1 + 0 + 1)


if __name__ == "__main__":
    unittest.main()
