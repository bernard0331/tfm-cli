"""The voice daemon: a Discord bot that sits in one voice channel for one tfm seat.

    python -m tfm.voice.bot --seat claude      (normally started by `tfm voice start`)

It transcribes what each person says into heard.jsonl and speaks whatever `tfm voice say` puts in the
outbox. See state.py for the files. Needs: pip install -e ".[voice]" and libopus (brew install opus).
"""
import argparse
import asyncio
import concurrent.futures
import ctypes.util
import io
import logging
import os
import signal
import sys
import threading
import time

import discord
from discord.ext import voice_recv

from . import audio, dave_patch, responder, state, stt, tts

log = logging.getLogger("tfm.voice")

VOICED_RMS = 350  # 20 ms frames quieter than this count as silence (open mics, breathing)


def load_opus():
    if discord.opus.is_loaded():
        return True
    for name in (ctypes.util.find_library("opus"), "/opt/homebrew/lib/libopus.dylib",
                 "/usr/local/lib/libopus.dylib", "libopus.so.0"):
        if not name:
            continue
        try:
            discord.opus.load_opus(name)
            return True
        except OSError:
            continue
    return False


class UtteranceSink(voice_recv.AudioSink):
    """Collects each speaker's audio and cuts it into utterances at pauses.

    write() runs on voice-recv's receive thread, so it only appends bytes; the bot's event loop
    polls pop_finished()."""

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.buffers = {}
        self.last_packet = 0.0

    def wants_opus(self):
        return False

    def write(self, user, data):
        if user is None or not data.pcm:
            return
        now = time.monotonic()
        self.last_packet = now
        loud = audio.rms(data.pcm) >= VOICED_RMS
        with self.lock:
            buf = self.buffers.get(user.id)
            if buf is None:
                if not loud:
                    return
                buf = self.buffers[user.id] = {"user": user, "pcm": bytearray(), "start": now, "last": now,
                                               "voiced": 0.0}
            buf["pcm"] += data.pcm
            if loud:
                buf["last"] = now
                buf["voiced"] += audio.duration(data.pcm)

    def pop_finished(self, silence_s, max_s):
        now = time.monotonic()
        done = []
        with self.lock:
            for uid, buf in list(self.buffers.items()):
                if now - buf["last"] >= silence_s or now - buf["start"] >= max_s:
                    done.append(self.buffers.pop(uid))
        return done

    def cleanup(self):
        pass


class VoiceBot(discord.Client):
    def __init__(self, seat):
        intents = discord.Intents.default()  # guilds + voice states; nothing privileged
        super().__init__(intents=intents)
        self.seat = seat
        self.paths = state.Paths(seat).ensure()
        self.cfg = state.load_config(self.paths)
        self.info = {"pid": os.getpid(), "seat": seat, "state": "starting", "started": time.time()}  # not .status: discord.Client owns that
        self.vc = None
        self.channel = None
        self.sink = UtteranceSink()
        self.transcriber = None
        self.voice = None
        self.stt_pool = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="stt")
        self.tts_pool = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="tts")
        self.llm_pool = concurrent.futures.ThreadPoolExecutor(2, thread_name_prefix="responder")
        self.responder = None
        self.speech = asyncio.Queue()
        self.interrupts = 0  # bumped by `voice say --interrupt` so a multi-sentence reply stops too
        self.last_spoke = 0.0  # monotonic time the bot last finished speaking, for follow-ups without a wake name
        self.pending = {}  # speaker -> auto-replies being written or waiting to be spoken
        self.stopping = False
        self.exit_code = 0

    # ------------------------------------------------------------ status

    def set_status(self, **kw):
        self.info.update(kw, updated=time.time())
        state.write_json(self.paths.status, self.info)

    def fail(self, message):
        log.error(message)
        self.set_status(state="error", error=message)
        self.exit_code = 1
        asyncio.get_running_loop().create_task(self.shutdown())

    def members(self):
        if not self.channel:
            return []
        return [{"name": m.display_name, "bot": m.bot} for m in self.channel.members if m.id != self.user.id]

    def heard(self, **entry):
        entry.setdefault("ts", time.time())
        state.append_jsonl(self.paths.heard, entry)

    # ------------------------------------------------------------ lifecycle

    async def setup_hook(self):
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: loop.create_task(self.shutdown()))
        loop.create_task(self.run_session())

    async def run_session(self):
        await self.wait_until_ready()
        loop = asyncio.get_running_loop()
        self.set_status(state="loading speech engines", bot_name=self.user.display_name)
        try:
            self.voice = await loop.run_in_executor(self.tts_pool, tts.make, self.cfg)
            self.transcriber = await loop.run_in_executor(self.stt_pool, stt.make, self.cfg)
        except Exception as e:
            return self.fail(f"speech engine: {e}")
        if responder.enabled(self.cfg):
            try:
                self.responder = responder.Responder(self.seat, self.cfg, self.paths)
            except RuntimeError as e:
                return self.fail(str(e))
        self.set_status(stt=self.transcriber.name, tts=self.voice.name,
                        responder=f"{self.responder.model}, {self.responder.share}" if self.responder else "off")

        channel_id = self.cfg.get("channel_id")
        try:
            self.channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden):
            return self.fail(f"can't see channel {channel_id}: is the bot invited to that server?")
        if not isinstance(self.channel, (discord.VoiceChannel, discord.StageChannel)):
            return self.fail(f"#{self.channel} is not a voice channel")

        await self.connect_voice()
        loop.create_task(self.segment_loop())
        loop.create_task(self.outbox_loop())
        loop.create_task(self.speak_loop())
        loop.create_task(self.watchdog())
        if self.responder:
            loop.create_task(self.game_refresh_loop())

    async def connect_voice(self):
        self.set_status(state="connecting", guild=self.channel.guild.name, channel=self.channel.name,
                        channel_id=self.channel.id, error=None)
        try:
            self.vc = await self.channel.connect(cls=voice_recv.VoiceRecvClient, self_deaf=False, timeout=30)
        except asyncio.TimeoutError:
            return self.fail("timed out joining voice: check the bot has Connect and Speak permission there")
        except discord.ClientException as e:
            return self.fail(f"joining voice failed: {e}")
        self.start_listening()
        self.set_status(state="listening", members=self.members())
        log.info("joined %s / %s", self.channel.guild.name, self.channel.name)

    def start_listening(self):
        self.sink = UtteranceSink()
        self.vc.listen(self.sink, after=lambda err: log.warning("receive stopped: %s", err) if err else None)

    async def shutdown(self):
        if self.stopping:
            return
        self.stopping = True
        log.info("shutting down")
        try:
            if self.vc and self.vc.is_connected():
                await self.vc.disconnect(force=True)
        except Exception:
            pass
        if self.info.get("state") != "error":
            self.set_status(state="stopped")
        await self.close()

    # ------------------------------------------------------------ listening

    def stt_prompt(self):
        people = ", ".join(m["name"] for m in self.members())
        return f"Players in the call: {people}. The bot is called {self.user.display_name}."

    async def segment_loop(self):
        loop = asyncio.get_running_loop()
        while not self.stopping:
            await asyncio.sleep(0.1)
            silence = self.cfg["silence_ms"] / 1000
            for utt in self.sink.pop_finished(silence, self.cfg["max_utterance_s"]):
                if utt["voiced"] * 1000 < self.cfg["min_speech_ms"]:
                    continue
                loop.create_task(self.transcribe(utt))

    async def transcribe(self, utt):
        loop = asyncio.get_running_loop()
        user = utt["user"]
        try:
            pcm16k = audio.discord_to_speech(bytes(utt["pcm"]))
            text = await loop.run_in_executor(self.stt_pool, self.transcriber.transcribe, pcm16k, self.stt_prompt())
        except Exception as e:
            log.warning("transcription failed: %s", e)
            self.set_status(error=f"transcription: {e}")
            return
        if not text:
            return
        names = state.wake_names(self.seat, self.cfg, self.info)
        direct = state.is_addressed(text, names)
        followup = not user.bot and time.monotonic() - self.last_spoke < self.cfg["followup_s"]
        addressed = direct or followup
        auto = bool(self.responder) and responder.should_reply(direct, followup, user.bot,
                                                               self.pending.get(user.display_name, 0))
        if self.responder and addressed and not direct and not auto:
            addressed = False  # a follow-up while their last reply is on its way: context, not a new question
        log.info("%s: %s", user.display_name, text)
        entry = dict(kind="voice", speaker=user.display_name, user_id=user.id, bot=user.bot, text=text,
                     addressed=addressed, direct=direct, auto=auto, seconds=round(utt["voiced"], 1), ts=time.time())
        self.heard(**entry)
        if auto:
            await self.auto_reply(entry)

    # ------------------------------------------------------------ table talk

    def reply_done(self, speaker):
        if speaker and self.pending.get(speaker):
            self.pending[speaker] -= 1

    async def auto_reply(self, entry):
        loop = asyncio.get_running_loop()
        t0 = time.monotonic()
        speaker = entry["speaker"]
        self.pending[speaker] = self.pending.get(speaker, 0) + 1
        try:
            kind, text = await loop.run_in_executor(self.llm_pool, self.responder.reply, speaker, entry["text"],
                                                    self.user.display_name, entry["direct"])
        except Exception as e:
            self.reply_done(speaker)
            log.warning("auto-reply failed: %s", e)
            self.set_status(error=f"responder: {e}")
            self.heard(kind="handoff", speaker=entry["speaker"], text=entry["text"], addressed=True,
                       reason="auto-reply failed")
            return
        log.info("auto-reply (%s, %.1fs): %s", kind, time.monotonic() - t0, text)
        if text:
            await self.speech.put({"id": f"auto-{time.time_ns()}", "text": text, "source": "auto", "speaker": speaker})
        else:
            self.reply_done(speaker)
        if kind == "defer":
            self.heard(kind="handoff", speaker=entry["speaker"], text=entry["text"], addressed=True,
                       reason="handed to you", ack=text)

    async def game_refresh_loop(self):
        """Keep the responder's game state fresh so a reply never waits on the game server."""
        loop = asyncio.get_running_loop()
        while not self.stopping:
            try:
                await loop.run_in_executor(self.llm_pool, self.responder.refresh)
            except Exception as e:
                log.debug("game refresh failed: %s", e)
            await asyncio.sleep(15)

    async def on_voice_state_update(self, member, before, after):
        if not self.channel or member.id == self.user.id:
            return
        if after.channel and after.channel.id == self.channel.id and (not before.channel or before.channel.id != self.channel.id):
            self.heard(kind="join", speaker=member.display_name, user_id=member.id, bot=member.bot)
        elif before.channel and before.channel.id == self.channel.id and (not after.channel or after.channel.id != self.channel.id):
            self.heard(kind="leave", speaker=member.display_name, user_id=member.id, bot=member.bot)
        self.set_status(members=self.members())

    # ------------------------------------------------------------ speaking

    async def outbox_loop(self):
        while not self.stopping:
            for msg in state.take_outbox(self.paths):
                if msg.get("interrupt"):
                    self.interrupts += 1
                    while not self.speech.empty():
                        self.reply_done(self.speech.get_nowait().get("speaker"))
                    if self.vc and self.vc.is_playing():
                        self.vc.stop_playing()
                await self.speech.put(msg)
            await asyncio.sleep(0.25)

    async def speak_loop(self):
        loop = asyncio.get_running_loop()
        while not self.stopping:
            msg = await self.speech.get()
            generation = self.interrupts
            try:
                if msg.get("also_text"):
                    await self.channel.send(msg["text"][:2000])
                # Synthesize sentence by sentence and start playing the first one while the rest render.
                parts = tts.sentences(tts.speakable(msg["text"]))
                pending = loop.run_in_executor(self.tts_pool, self.voice.synth, parts[0])
                for i in range(len(parts)):
                    pcm = await pending
                    if self.interrupts != generation:
                        break
                    if i + 1 < len(parts):
                        pending = loop.run_in_executor(self.tts_pool, self.voice.synth, parts[i + 1])
                    await self.play_pcm(pcm)
            except Exception as e:
                log.warning("speech failed: %s", e)
                self.set_status(error=f"speech: {e}")
                state.append_jsonl(self.paths.said, {"id": msg["id"], "ts": time.time(), "error": str(e)})
                continue
            finally:
                self.reply_done(msg.get("speaker"))
            self.last_spoke = time.monotonic()
            state.append_jsonl(self.paths.said, {"id": msg["id"], "ts": time.time(), "text": msg["text"]})
            self.heard(kind="said", source=msg.get("source", "agent"), text=msg["text"])

    async def play_pcm(self, pcm):
        loop = asyncio.get_running_loop()
        while self.vc is None or not self.vc.is_connected():
            await asyncio.sleep(0.5)
        done = asyncio.Event()
        source = discord.PCMVolumeTransformer(discord.PCMAudio(io.BytesIO(pcm)),
                                              volume=float(self.cfg.get("volume") or 1.0))
        if self.vc.is_playing():
            self.vc.stop_playing()
        self.vc.play(source, after=lambda err: loop.call_soon_threadsafe(done.set))
        await done.wait()

    # ------------------------------------------------------------ keep alive

    async def watchdog(self):
        down_since = None
        while not self.stopping:
            await asyncio.sleep(5)
            if self.vc is None:
                continue
            if not self.vc.is_connected():
                down_since = down_since or time.monotonic()
                self.set_status(state="reconnecting")
                if time.monotonic() - down_since > 30:  # discord.py's own reconnect gave up
                    log.warning("voice connection lost; rejoining")
                    try:
                        await self.vc.disconnect(force=True)
                    except Exception:
                        pass
                    down_since = None
                    await self.connect_voice()
                continue
            down_since = None
            if not self.vc.is_listening():
                log.warning("receive thread stopped; restarting it")
                self.start_listening()
            if self.info.get("state") != "listening":
                self.set_status(state="listening", members=self.members())


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m tfm.voice.bot")
    parser.add_argument("--seat", required=True)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("discord").setLevel(logging.INFO if args.debug else logging.WARNING)

    paths = state.Paths(args.seat).ensure()
    other = state.daemon_pid(paths)
    if other and other != os.getpid():
        print(f"voice daemon for {args.seat} already running (pid {other})", file=sys.stderr)
        return 1
    paths.pid.write_text(str(os.getpid()))

    def early_fail(msg):
        state.write_json(paths.status, {"pid": os.getpid(), "seat": args.seat, "state": "error", "error": msg,
                                        "updated": time.time()})
        log.error(msg)
        return 1

    try:
        cfg = state.load_config(paths)
        token = state.token(cfg)
        if not token:
            return early_fail("no bot token: run `tfm voice config` (or set DISCORD_BOT_TOKEN)")
        if not cfg.get("channel_id"):
            return early_fail("no voice channel: run `tfm voice config --channel <link>`")
        if not load_opus():
            return early_fail("libopus not found: brew install opus")
        log.info("DAVE receive: %s", dave_patch.apply())
        bot = VoiceBot(args.seat)
        try:
            bot.run(token, log_handler=None)
        except discord.LoginFailure:
            return early_fail("Discord rejected the bot token: reset it in the Developer Portal and rerun `tfm voice config`")
        except discord.PrivilegedIntentsRequired as e:
            return early_fail(f"Discord refused intents: {e}")
        except Exception as e:  # network down, Discord outage, a bug: say so in `voice status`
            log.exception("voice daemon crashed")
            return early_fail(f"crashed: {e!r} (see {paths.log})")
        return bot.exit_code
    finally:
        try:
            if paths.pid.read_text().strip() == str(os.getpid()):
                paths.pid.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
