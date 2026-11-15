"""Checks for `tfm archive`. Run: python3 -m unittest discover tests"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tfm import archive, cli, seats
from tfm.client import TfmError

SPECTATOR = "s0123456789abcdef"
RED_ID, BLUE_ID = "p1111111111aaaa", "p2222222222bbbb"


def view(color="red", phase="end", generation=2):
    players = [{"name": "claude", "color": "red", "id": RED_ID,
                "victoryPointsBreakdown": {"total": 60, "terraformRating": 30, "milestones": 5, "awards": 5,
                                           "greenery": 6, "city": 8, "victoryPoints": 6, "escapeVelocity": 0}},
               {"name": "gpt", "color": "blue", "id": BLUE_ID,
                "victoryPointsBreakdown": {"total": 50, "terraformRating": 28, "milestones": 0, "awards": 5,
                                           "greenery": 4, "city": 6, "victoryPoints": 7, "escapeVelocity": 0}}]
    me = next(p for p in players if p["color"] == color)
    return {"id": me["id"], "thisPlayer": me, "players": players,
            "game": {"name": "Polar Test Link", "phase": phase, "generation": generation,
                     "spectatorId": SPECTATOR, "gameOptions": {"boardName": "tharsis"}}}


class FakeClient:
    """Stands in for the server: one player view and a log per generation."""

    def __init__(self, view, logs=None, error=None):
        self.view, self.error, self.log_calls = view, error, []
        self.all_logs = logs or {1: [{"timestamp": 10, "message": "gen 1", "data": [], "playerId": RED_ID}],
                                 2: [{"timestamp": 20, "message": "gen 2", "data": []}]}

    def player(self):
        if self.error:
            raise TfmError(self.error)
        return self.view

    def logs(self, generation=None):
        self.log_calls.append(generation)
        return self.all_logs.get(generation, [])


class ArchiveCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"TFM_HOME": tmp.name})
        patch.start()
        self.addCleanup(patch.stop)
        self.home = Path(tmp.name)
        self.seat = {"name": "claude", "server": "https://example.test", "player_id": RED_ID, "game": "Polar Test Link"}


class Save(ArchiveCase):
    def test_finished_game_is_saved_under_tfm_home_with_every_generation_log(self):
        client = FakeClient(view())
        path, created = archive.save(client, self.seat)
        self.assertTrue(created)
        self.assertEqual(path.parent, self.home / "games")
        self.assertTrue(path.name.startswith("polar-test-link-"))
        record = json.loads(path.read_text())
        self.assertEqual(record["format"], archive.FORMAT)
        self.assertEqual(record["generations"], 2)
        self.assertEqual(sorted(record["logs"]), ["1", "2"])
        self.assertEqual(client.log_calls, [1, 2])
        saved = record["views"]["red"]
        self.assertEqual(saved["seat"], "claude")
        self.assertEqual(saved["view"]["players"][0]["victoryPointsBreakdown"]["total"], 60)

    def test_player_and_spectator_ids_are_never_written(self):
        path, _ = archive.save(FakeClient(view()), self.seat)
        text = path.read_text()
        for secret in (RED_ID, BLUE_ID, SPECTATOR):
            self.assertNotIn(secret, text)
        self.assertIn(archive.REDACTED, text)

    def test_unfinished_game_is_refused_and_nothing_is_written(self):
        with self.assertRaisesRegex(TfmError, "is not finished"):
            archive.save(FakeClient(view(phase="action")), self.seat)
        self.assertEqual(list((self.home / "games").glob("*")), [])

    def test_archiving_again_keeps_one_file_and_does_not_duplicate_logs(self):
        first, _ = archive.save(FakeClient(view()), self.seat)
        second, created = archive.save(FakeClient(view()), self.seat)
        self.assertEqual(first, second)
        self.assertFalse(created)
        record = json.loads(second.read_text())
        self.assertEqual(len(record["logs"]["1"]), 1)
        self.assertEqual(list(record["views"]), ["red"])
        self.assertEqual(len(list((self.home / "games").glob("*"))), 1)

    def test_a_second_seat_in_the_same_game_adds_its_view_and_private_log_entries(self):
        archive.save(FakeClient(view("red")), self.seat)
        blue_logs = {1: [{"timestamp": 10, "message": "gen 1", "data": [], "playerId": RED_ID},
                         {"timestamp": 5, "message": "blue drew a card", "data": []}], 2: []}
        blue_seat = dict(self.seat, name="gpt", player_id=BLUE_ID)
        path, created = archive.save(FakeClient(view("blue"), blue_logs), blue_seat)
        self.assertFalse(created)
        record = json.loads(path.read_text())
        self.assertEqual(sorted(record["views"]), ["blue", "red"])
        self.assertEqual([e["message"] for e in record["logs"]["1"]], ["blue drew a card", "gen 1"])
        self.assertEqual(len(record["logs"]["2"]), 1)

    def test_a_damaged_archive_file_is_not_overwritten(self):
        path, _ = archive.save(FakeClient(view()), self.seat)
        path.write_text("{ not json")
        with self.assertRaisesRegex(TfmError, "not valid JSON"):
            archive.save(FakeClient(view()), self.seat)
        self.assertEqual(path.read_text(), "{ not json")


class Backfill(ArchiveCase):
    def test_every_seat_is_tried_and_a_game_the_server_dropped_is_reported(self):
        clients = {RED_ID: FakeClient(view("red")),
                   BLUE_ID: FakeClient(None, error="server rejected request (404): Not found"),
                   "p3333333333cccc": FakeClient(view(phase="action"))}
        for name, pid in (("claude", RED_ID), ("gone", BLUE_ID), ("live", "p3333333333cccc")):
            seats.save({"name": name, "server": "https://example.test", "player_id": pid, "game": f"game of {name}"})
        with mock.patch.object(archive, "Client", lambda server, pid: clients[pid]):
            results = {name: (outcome, detail) for name, _, outcome, detail in archive.save_all()}
        self.assertEqual(results["claude"][0], "archived")
        self.assertEqual(results["gone"][0], "failed")
        self.assertIn("no longer has this game", results["gone"][1])
        self.assertEqual(results["live"][0], "not finished")
        self.assertEqual(len(list((self.home / "games").glob("*.json"))), 1)


class GameOver(ArchiveCase):
    """`tfm turn` and `tfm state` call this after printing the final scores."""

    def run_hook(self, client):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli._archive_quietly(client, self.seat, client.view)
        return out.getvalue(), err.getvalue()

    def test_seeing_game_over_archives_once(self):
        client = FakeClient(view())
        out, _ = self.run_hook(client)
        self.assertIn("Archived this game to", out)
        calls = len(client.log_calls)
        out, _ = self.run_hook(client)
        self.assertEqual(out, "")
        self.assertEqual(len(client.log_calls), calls)

    def test_a_failed_archive_only_warns(self):
        client = FakeClient(view())
        client.logs = mock.Mock(side_effect=TfmError("cannot reach server"))
        out, err = self.run_hook(client)
        self.assertEqual(out, "")
        self.assertIn("WARNING: could not archive", err)
        self.assertEqual(list((self.home / "games").glob("*")), [])


if __name__ == "__main__":
    unittest.main()
