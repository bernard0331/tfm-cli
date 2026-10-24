"""Checks for how tfm describes board spaces. Run: python3 -m unittest discover tests"""
import types
import unittest

from tfm import data, options

BOARD = "terra cimmeria nova"
MILD_EROSION, SEVERE_DUST_STORM, CITY = 25, 24, 2


def ctx(spaces):
    return types.SimpleNamespace(board_name=BOARD, spaces={s["id"]: s for s in spaces},
                                 me={"color": "red"}, names={"blue": "rival"})


class DescribeSpace(unittest.TestCase):
    def test_hazard_on_the_space_shows_its_fee_and_tr(self):
        text = options.describe_space("46", ctx([{"id": "46", "spaceType": "land", "tileType": MILD_EROSION}]))
        self.assertIn("ON Mild Erosion: costs 8 M€ extra, +1 TR", text)

    def test_adjacent_hazards_show_the_production_loss(self):
        a, b, c = data.adjacency(BOARD, "46")[:3]
        spaces = [{"id": "46", "spaceType": "land"}, {"id": a, "tileType": MILD_EROSION},
                  {"id": b, "tileType": SEVERE_DUST_STORM}, {"id": c, "tileType": CITY, "color": "blue"}]
        text = options.describe_space("46", ctx(spaces))
        self.assertIn("next to hazard: lose 3 production", text)
        self.assertNotIn("ON ", text)

    def test_plain_space_has_no_hazard_note(self):
        text = options.describe_space("46", ctx([{"id": "46", "spaceType": "land"}]))
        self.assertNotIn("hazard", text)
        self.assertNotIn("ON ", text)


class ClaimedUndergroundToken(unittest.TestCase):
    NODE = {"type": "claimedUndergroundToken", "min": 1, "max": 1,
            "tokens": [{"token": "plant2pertemp", "shelter": True, "active": False},
                       {"token": "nothing", "shelter": False, "active": True}]}

    def test_server_token_dicts_are_listed_by_index(self):
        # Underground Shelters' action: the server sends ClaimedToken objects, not names.
        text = options.needs(self.NODE, ctx([]))
        self.assertIn("0:plant2pertemp (this generation: +2 plants", text)
        self.assertIn("[shelter]", text)
        self.assertIn("1:nothing [active]", text)

    def test_bare_token_names_still_work(self):
        text = options.needs(dict(self.NODE, tokens=["steel2plant"]), ctx([]))
        self.assertIn("0:steel2plant (2 steel and 1 plant)", text)


if __name__ == "__main__":
    unittest.main()
