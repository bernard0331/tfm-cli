"""Checks for the voice chat plumbing that doesn't need Discord. Run: python3 -m unittest discover tests"""
import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from tfm import cli, seats
from tfm.client import TfmError
from tfm.voice import audio, responder, state, stt, tts
from tfm.voice import cli as voice


class TempHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TFM_HOME": self.tmp.name})
        self.env.start()
        self.paths = state.Paths("claude").ensure()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def pretend_running(self):
        self.paths.pid.write_text(str(os.getpid()))

    def hear(self, text, addressed=False, bot=False, speaker="Ken"):
        state.append_jsonl(self.paths.heard, {"ts": time.time(), "kind": "voice", "speaker": speaker,
                                              "text": text, "addressed": addressed, "bot": bot})


class Channel(unittest.TestCase):
    def test_link(self):
        self.assertEqual(state.parse_channel("https://discord.com/channels/123456789012345678/876543210987654321"),
                         (123456789012345678, 876543210987654321))

    def test_bad_link(self):
        with self.assertRaises(TfmError):
            state.parse_channel("general")


class WakeNames(unittest.TestCase):
    def test_soundalikes_and_custom_names(self):
        names = state.wake_names("claude", {"names": ["Robo"]}, {"bot_name": "TFM Claude"})
        for text in ("Hey Claude, what are you going for?", "cloud, your turn", "robo?", "ok tfm claude"):
            self.assertTrue(state.is_addressed(text, names), text)

    def test_no_partial_words(self):
        names = state.wake_names("claude", {}, None)
        self.assertFalse(state.is_addressed("the clouds are nice", names))
        self.assertFalse(state.is_addressed("I'll play Birds", names))


class HeardLog(TempHome):
    def test_unread_advances_and_ignores_half_lines(self):
        self.hear("one")
        with open(self.paths.heard, "a") as f:
            f.write('{"kind": "voice", "text": "half')
        self.assertEqual([e["text"] for e in state.unread(self.paths)], ["one"])
        self.assertEqual(state.unread(self.paths), [])
        with open(self.paths.heard, "a") as f:
            f.write(' written"}\n')
        self.assertEqual([e["text"] for e in state.unread(self.paths)], ["half written"])

    def test_peek_does_not_advance(self):
        self.hear("hello")
        state.unread(self.paths, advance=False)
        self.assertEqual(len(state.unread(self.paths)), 1)

    def test_skip_to_end(self):
        self.hear("old")
        state.skip_to_end(self.paths)
        self.hear("new")
        self.assertEqual([e["text"] for e in state.unread(self.paths)], ["new"])

    def test_format(self):
        line = state.format_entry({"ts": 0, "speaker": "Ken", "kind": "join"})
        self.assertIn("Ken joined the voice channel", line)


class Outbox(TempHome):
    def test_fifo_and_said(self):
        a = state.queue_say(self.paths, "first")
        time.sleep(0.001)
        state.queue_say(self.paths, "second", interrupt=True)
        msgs = state.take_outbox(self.paths)
        self.assertEqual([m["text"] for m in msgs], ["first", "second"])
        self.assertTrue(msgs[1]["interrupt"])
        self.assertEqual(state.take_outbox(self.paths), [])
        self.assertIsNone(state.was_said(self.paths, a))
        state.append_jsonl(self.paths.said, {"id": a, "text": "first"})
        self.assertEqual(state.was_said(self.paths, a)["text"], "first")


class Config(TempHome):
    def test_token_file_is_private_and_defaults_not_stored(self):
        cfg = state.load_config(self.paths)
        cfg["token"] = "abc"
        state.save_config(self.paths, cfg)
        self.assertEqual(oct(self.paths.config.stat().st_mode & 0o777), "0o600")
        self.assertEqual(json.loads(self.paths.config.read_text()), {"token": "abc"})

    def test_config_command(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["-s", "claude", "voice", "config", "--token", "x" * 30,
                      "--channel", "https://discord.com/channels/111111111111111111/222222222222222222",
                      "--name", "Robo"])
        cfg = state.load_config(self.paths)
        self.assertEqual(cfg["channel_id"], 222222222222222222)
        self.assertEqual(cfg["names"], ["robo"])
        self.assertIn("Ready: tfm -s claude voice start", out.getvalue())
        self.assertNotIn("x" * 30, out.getvalue())


class Hooks(TempHome):
    def test_off_prints_nothing(self):
        self.hear("hi")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(voice.print_unread("claude"), [])
        self.assertEqual(out.getvalue(), "")

    def test_block_and_addressed_hint(self):
        self.pretend_running()
        self.hear("nice greenery")
        self.hear("claude, why the ocean?", addressed=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            voice.print_unread("claude")
        text = out.getvalue()
        self.assertIn("VOICE CHAT (since your last look):", text)
        self.assertIn("Ken: nice greenery", text)
        self.assertIn('YOU WERE ADDRESSED. Answer out loud: tfm -s claude voice say', text)

    def test_bots_do_not_wake_the_agent(self):
        self.pretend_running()
        self.hear("claude, your move", addressed=True, bot=True, speaker="GPT")
        self.assertFalse(voice.addressed_pending(self.paths))
        self.hear("claude?", addressed=True)
        self.assertTrue(voice.addressed_pending(self.paths))

    def test_turn_wait_wakes_early(self):
        self.pretend_running()
        self.hear("claude?", addressed=True)
        t0 = time.time()
        self.assertTrue(cli._sleep_unless_addressed(self.paths, 3))
        self.assertLess(time.time() - t0, 1)

    def test_turn_wait_without_voice_just_sleeps(self):
        with mock.patch.object(cli.time, "sleep") as sleep:
            self.assertFalse(cli._sleep_unless_addressed(None, 3))
        sleep.assert_called_once_with(3)

    def test_say_needs_daemon(self):
        with self.assertRaises(TfmError):
            cli_args = type("A", (), {"seat": "claude", "text": ["hi"], "interrupt": False, "text_chat": False,
                                      "wait": False})()
            voice.cmd_say(cli_args)


class Audio(unittest.TestCase):
    def test_to_discord_pads_whole_frames(self):
        pcm = audio.to_discord(b"\x01\x00" * 24000, 24000, 1)  # 1 s at 24 kHz mono
        self.assertEqual(len(pcm) % audio.FRAME_BYTES, 0)
        self.assertAlmostEqual(audio.duration(pcm), 1.0, delta=0.03)

    def test_discord_to_speech(self):
        pcm = b"\x00\x10" * (48000 * 2)  # 1 s of 48 kHz stereo
        self.assertAlmostEqual(len(audio.discord_to_speech(pcm)) / 2 / 16000, 1.0, delta=0.01)

    def test_wav_round_trip(self):
        data = audio.wav_bytes(b"\x00\x01" * 160)
        pcm, rate, ch = audio.read_wav(data)
        self.assertEqual((len(pcm), rate, ch), (320, 16000, 1))


class Text(unittest.TestCase):
    def test_speakable(self):
        self.assertEqual(tts.speakable("**Pay 12 M€** for `Birds` → +1 TR"),
                         "Pay 12 megacredits for Birds to +1 T R")

    def test_hallucinations_dropped(self):
        self.assertEqual(stt.clean(" Thank you. "), "")
        self.assertEqual(stt.clean("Thank you, Claude, nice move"), "Thank you, Claude, nice move")


class TableTalk(TempHome):
    def test_auto_lines_dont_wake_the_agent_but_handoffs_do(self):
        self.pretend_running()
        state.append_jsonl(self.paths.heard, {"kind": "voice", "speaker": "Ken", "text": "claude, who's winning?",
                                              "addressed": True, "auto": True, "ts": time.time()})
        self.assertFalse(voice.addressed_pending(self.paths))
        state.append_jsonl(self.paths.heard, {"kind": "handoff", "speaker": "Ken", "text": "claude, undo that",
                                              "addressed": True, "ts": time.time()})
        self.assertTrue(voice.addressed_pending(self.paths))

    def test_block_shows_auto_replies_not_own_say(self):
        self.pretend_running()
        for e in ({"kind": "said", "source": "agent", "text": "I said this myself"},
                  {"kind": "said", "source": "auto", "text": "Ken is ahead on TR"},
                  {"kind": "handoff", "speaker": "Ken", "text": "claude, trade with me?", "addressed": True}):
            state.append_jsonl(self.paths.heard, {**e, "ts": time.time()})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            voice.print_unread("claude")
        text = out.getvalue()
        self.assertNotIn("I said this myself", text)
        self.assertIn("YOU (table-talk auto-reply): Ken is ahead on TR", text)
        self.assertIn("Ken asked you (needs YOUR answer): claude, trade with me?", text)
        self.assertIn("YOU WERE ADDRESSED", text)

    def test_only_own_say_prints_nothing(self):
        self.pretend_running()
        state.append_jsonl(self.paths.heard, {"kind": "said", "source": "agent", "text": "hi", "ts": time.time()})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            voice.print_unread("claude", leading_blank=True)
        self.assertEqual(out.getvalue(), "")

    def test_parse_reply(self):
        self.assertEqual(responder.parse_reply("DEFER: Give me a sec."), ("defer", "Give me a sec."))
        self.assertEqual(responder.parse_reply("defer"), ("defer", "Give me a second on that one."))
        self.assertEqual(responder.parse_reply(' "Ken is way ahead, honestly." '), ("answer", "Ken is way ahead, honestly."))

    def test_parse_reply_skip_and_empty(self):
        for raw in ("SKIP", "skip.", " (SKIP) ", "[skip]", "", None, '""', "   "):
            self.assertEqual(responder.parse_reply(raw), ("skip", ""), raw)
        self.assertEqual(responder.parse_reply("Skip the hellos, got it."), ("answer", "Skip the hellos, got it."))

    def test_followup_gating(self):
        self.assertTrue(responder.should_reply(direct=True, followup=False, from_bot=False, pending=0))
        self.assertTrue(responder.should_reply(direct=True, followup=True, from_bot=False, pending=1))
        self.assertTrue(responder.should_reply(direct=False, followup=True, from_bot=False, pending=0))
        self.assertFalse(responder.should_reply(direct=False, followup=True, from_bot=False, pending=1))
        self.assertFalse(responder.should_reply(direct=False, followup=False, from_bot=False, pending=0))
        self.assertFalse(responder.should_reply(direct=True, followup=True, from_bot=True, pending=0))

    def test_passed_line(self):
        view = {"game": {"generation": 2, "phase": "action", "passedPlayers": ["red"]}, "thisPlayer": {"color": "red"}}
        self.assertIn("You have PASSED", responder.passed_line(view))
        view["thisPlayer"]["color"] = "blue"
        self.assertIn("NOT passed", responder.passed_line(view))
        view["game"]["phase"] = "drafting"
        self.assertIn("aren't done", responder.passed_line(view))

    def test_enabled(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.assertFalse(responder.enabled({"responder": "auto"}))
            self.assertTrue(responder.enabled({"responder": "auto", "anthropic_key": "k"}))
            self.assertFalse(responder.enabled({"responder": "off", "anthropic_key": "k"}))

    def test_private_summary_never_contains_the_hand(self):
        view = {"game": {"generation": 3, "phase": "action"}, "cardsInHand": [{}, {}],
                "waitingFor": None, "thisPlayer": {}, "players": []}
        chunks = [("game", True, ["GAME x"]), ("hand", False, ["  HAND (2):", "    Birds", "    Kelp Farming"]),
                  ("draftedCards", False, ["  DRAFTED: Mangrove"]), ("opps", True, ["OPPONENTS:"])]
        seats.save({"name": "claude", "server": "http://x", "player_id": "p1", "award_scores": {}})
        with mock.patch.object(responder, "Client") as client, \
                mock.patch.object(responder.options, "Context", return_value=type("C", (), {"names": {}})()), \
                mock.patch.object(responder.digest, "sections", return_value=chunks):
            client.return_value.player.return_value = view
            client.return_value.logs.return_value = [{"message": "Ken placed an ocean", "data": []}]
            private = responder.game_summary("claude", "private")
            opened = responder.game_summary("claude", "open")
        for card in ("Birds", "Kelp Farming", "Mangrove"):
            self.assertNotIn(card, private)
            self.assertIn(card, opened)
        self.assertIn("HAND: 2 cards (contents withheld from you)", private)
        self.assertIn("Ken placed an ocean", private)

    def test_reply_request(self):
        voice.set_notes("claude", "Took the ocean for the card draw.")
        state.append_jsonl(self.paths.heard, {"kind": "voice", "speaker": "Ken", "text": "nice ocean", "ts": time.time()})
        r = responder.Responder("claude", {**state.DEFAULTS, "anthropic_key": "sk-test"}, self.paths)
        r.summary, r.summary_at = "GAME STATE HERE", time.time()
        sent = {}

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout):
            sent["headers"] = dict(req.header_items())
            sent["body"] = json.loads(req.data)
            return Resp(json.dumps({"content": [{"type": "text", "text": "Thanks, it drew me a card!"}]}).encode())

        with mock.patch.object(responder.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual(r.reply("Ken", "claude why the ocean?", "TFM Claude"),
                             ("answer", "Thanks, it drew me a card!"))
        body = sent["body"]
        self.assertEqual(body["model"], "claude-haiku-5-5")
        self.assertEqual(sent["headers"]["X-api-key"], "sk-test")
        self.assertEqual(sent["headers"]["Anthropic-version"], "2023-06-01")
        self.assertIn("PRIVACY", body["system"])
        msg = body["messages"][0]["content"]
        for part in ("GAME STATE HERE", "Took the ocean for the card draw.", "Ken: nice ocean", "claude why the ocean?"):
            self.assertIn(part, msg)

    def fake_api(self, *replies):
        """Responder whose API calls return these texts in order (an Exception instance is raised instead)."""
        r = responder.Responder("claude", {**state.DEFAULTS, "anthropic_key": "sk-test"}, self.paths)
        r.summary, r.summary_at = "GAME STATE HERE", time.time()
        bodies, queue = [], list(replies)

        def post(body):
            bodies.append(body)
            reply = queue.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return {"stop_reason": "end_turn", "content": [{"type": "thinking", "thinking": ""}] +
                    ([{"type": "text", "text": reply}] if reply else [])}

        r._post = post
        return r, bodies

    def test_thinking_is_off_and_empty_direct_reply_retries(self):
        r, bodies = self.fake_api("", "Nope, I passed already.")
        self.assertEqual(r.reply("Ken", "claude, are you done?", "TFM Claude"), ("answer", "Nope, I passed already."))
        self.assertEqual(bodies[0]["thinking"], {"type": "disabled"})
        self.assertEqual(len(bodies), 2)
        self.assertIn("SKIP and silence aren't options", bodies[1]["messages"][0]["content"])

    def test_direct_line_never_ends_silent(self):
        r, _ = self.fake_api("", "SKIP")
        kind, text = r.reply("Ken", "claude, are you done?", "TFM Claude")
        self.assertEqual(kind, "defer")
        self.assertTrue(text)

    def test_followup_can_skip(self):
        r, bodies = self.fake_api("SKIP")
        self.assertEqual(r.reply("Ken", "Quad.", "TFM Claude", direct=False), ("skip", ""))
        self.assertEqual(len(bodies), 1)
        self.assertIn("FOLLOW-UP", bodies[0]["messages"][0]["content"])

    def test_model_that_rejects_disabled_thinking(self):
        r, bodies = self.fake_api(responder._ThinkingRejected("thinking.type: disabled not supported"), "Sure.")
        self.assertEqual(r.reply("Ken", "claude?", "TFM Claude"), ("answer", "Sure."))
        self.assertNotIn("thinking", bodies[1])
        self.assertEqual(bodies[1]["output_config"], {"effort": "low"})
        self.assertFalse(r.thinking_off)

    def test_sentences(self):
        self.assertEqual(tts.sentences("Yes. I took the ocean because it drew a card. Ken is ahead though!"),
                         ["Yes. I took the ocean because it drew a card.", "Ken is ahead though!"])


if __name__ == "__main__":
    unittest.main()
