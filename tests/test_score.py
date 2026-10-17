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


if __name__ == "__main__":
    unittest.main()
