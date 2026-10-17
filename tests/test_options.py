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


if __name__ == "__main__":
    unittest.main()
