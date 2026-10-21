"""`tfm voice ...` commands, and the hooks that show voice chat inside `tfm turn` / `state` / `play`.

Standard library only: the Discord side runs in a separate daemon process (bot.py)."""
import getpass
import importlib.util
import os
import subprocess
import sys
import time

from .. import seats
from ..client import TfmError
from . import responder, state


def seat_name(args):
    """Voice is configured per seat name; the seat doesn't have to have joined a game yet."""
    name = args.seat or os.environ.get("TFM_SEAT")
    if name:
        return state.slug(name)
    candidates = seats.names() or state.configured_seats()
    if len(candidates) == 1:
        return candidates[0]
    raise TfmError("pass the seat name: tfm -s <seat> voice ...")


def _mask(tok):
    return f"{tok[:6]}…{tok[-4:]}" if tok and len(tok) > 12 else ("set" if tok else "not set")


# ------------------------------------------------------------------ commands

def _clean_errors(fn):
    """Engine and API problems are expected (no key, no network): report them like other tfm errors."""
    def wrapper(args):
        try:
            return fn(args)
        except RuntimeError as e:
            raise TfmError(str(e)) from None
    wrapper.__doc__ = fn.__doc__
    return wrapper



def cmd_config(args):
    name = seat_name(args)
    paths = state.Paths(name).ensure()
    cfg = state.load_config(paths)
    if args.channel:
        cfg["guild_id"], cfg["channel_id"] = state.parse_channel(args.channel)
    if args.token:
        cfg["token"] = args.token.strip()
    elif not state.token(cfg) and sys.stdin.isatty():
        cfg["token"] = getpass.getpass("Discord bot token (input hidden): ").strip() or None
    for key in ("stt", "tts", "voice", "rate", "volume", "whisper_model", "language", "silence_ms",
                "responder", "responder_model", "share"):
        val = getattr(args, key, None)
        if val is not None:
            cfg[key] = val
    if args.openai_key:
        cfg["openai_key"] = args.openai_key.strip()
    if args.anthropic_key:
        cfg["anthropic_key"] = args.anthropic_key.strip()
    if args.name:
        cfg["names"] = sorted(set(cfg.get("names") or []) | {n.lower() for n in args.name})
    if args.clear_names:
        cfg["names"] = []
    state.save_config(paths, cfg)

    print(f"Voice config for seat '{name}' ({paths.config}):")
    print(f"  bot token:   {_mask(state.token(cfg))}")
    print(f"  channel:     {cfg['guild_id']}/{cfg['channel_id']}" if cfg.get("channel_id") else "  channel:     not set")
    print(f"  stt / tts:   {cfg['stt']} / {cfg['tts']}" + (f" (voice {cfg['voice']})" if cfg.get("voice") else ""))
    print(f"  openai key:  {_mask(state.openai_key(cfg))}")
    print(f"  table talk:  {_responder_line(cfg)}")
    print(f"  wake names:  {', '.join(state.wake_names(name, cfg))}")
    missing = [w for w, ok in (("bot token", state.token(cfg)), ("channel", cfg.get("channel_id"))) if not ok]
    if missing:
        print(f"Still needed: {', '.join(missing)}.")
    else:
        print(f"Ready: tfm -s {name} voice start")


def _responder_line(cfg):
    if responder.enabled(cfg):
        return f"on ({cfg['responder_model']}, {cfg['share']}: " + (
            "hand and plans hidden)" if cfg["share"] == "private" else "open hand)")
    if cfg.get("responder") == "off":
        return "off"
    return "off (set ANTHROPIC_API_KEY or --anthropic-key for fast auto-replies)"


def _deps_missing():
    try:
        missing = [m for m in ("discord", "discord.ext.voice_recv", "davey", "nacl")
                   if importlib.util.find_spec(m) is None]
    except (ImportError, ValueError):
        missing = ["discord"]
    return missing


def cmd_start(args):
    name = seat_name(args)
    paths = state.Paths(name).ensure()
    cfg = state.load_config(paths)
    pid = state.daemon_pid(paths)
    if pid:
        print(f"Voice is already running for '{name}' (pid {pid}).")
        return _print_status(paths, name)
    if not state.token(cfg) or not cfg.get("channel_id"):
        raise TfmError(f"voice isn't configured yet: tfm -s {name} voice config --channel <voice channel link>")
    missing = _deps_missing()
    if missing:
        raise TfmError(f"missing Python packages ({', '.join(missing)}). From the tfm-cli folder run: "
                       f"{sys.executable} -m pip install -e \".[voice]\"")

    state.skip_to_end(paths)  # don't replay chatter from an earlier session
    state.take_outbox(paths)
    state.write_json(paths.status, {"state": "launching", "updated": time.time()})
    cmd = [sys.executable, "-m", "tfm.voice.bot", "--seat", name] + (["--debug"] if args.debug else [])
    with open(paths.log, "a") as log:
        log.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} starting\n")
        log.flush()
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True, env={**os.environ, "PYTHONUNBUFFERED": "1"})

    deadline = time.time() + args.wait
    st = {}
    while time.time() < deadline:
        time.sleep(0.5)
        st = state.read_json(paths.status, {}) or {}
        if st.get("state") in ("listening", "error", "stopped") or proc.poll() is not None:
            break
    if st.get("state") == "listening":
        print(f"Voice is on: '{name}' joined #{st.get('channel')} in {st.get('guild')} "
              f"(stt {st.get('stt')}, tts {st.get('tts')}).")
        _print_members(st)
        print(f"Speak: tfm -s {name} voice say \"...\"   Hear: tfm -s {name} voice listen   "
              f"(tfm turn also shows voice chat)")
        return
    if proc.poll() is None and st.get("state") != "error":
        print(f"Voice daemon started (pid {proc.pid}) but is still '{st.get('state', 'starting')}'. "
              f"Check with: tfm -s {name} voice status")
        return
    err = st.get("error") or _log_tail(paths)
    raise TfmError(f"voice daemon failed to start: {err}")


def _log_tail(paths, n=8):
    try:
        lines = paths.log.read_text(errors="replace").splitlines()[-n:]
    except OSError:
        return "no log"
    return "\n  " + "\n  ".join(lines)


def _print_members(st):
    members = st.get("members") or []
    if members:
        print("In the channel: " + ", ".join(m["name"] + (" (bot)" if m.get("bot") else "") for m in members))
    else:
        print("Nobody else is in the channel yet.")


def _print_status(paths, name):
    st = state.read_json(paths.status, {}) or {}
    pid = state.daemon_pid(paths)
    if not pid:
        print(f"Voice is off for '{name}'." + (f" Last error: {st['error']}" if st.get("state") == "error" else ""))
        return
    age = time.time() - st.get("started", time.time())
    print(f"Voice for '{name}': {st.get('state')} (pid {pid}, up {int(age // 60)} min) · #{st.get('channel')} "
          f"in {st.get('guild')} · stt {st.get('stt')} · tts {st.get('tts')} · table talk {st.get('responder', 'off')}")
    _print_members(st)
    if st.get("error"):
        print(f"Last error: {st['error']}")
    pending = len(state.unread(paths, advance=False))
    if pending:
        print(f"{pending} unread voice line(s): tfm -s {name} voice listen")


def cmd_status(args):
    name = seat_name(args)
    _print_status(state.Paths(name), name)


def cmd_stop(args):
    name = seat_name(args)
    paths = state.Paths(name)
    print(f"Voice stopped for '{name}'." if state.stop_daemon(paths) else f"Voice wasn't running for '{name}'.")


def cmd_say(args):
    name = seat_name(args)
    paths = state.Paths(name)
    if not state.daemon_pid(paths):
        raise TfmError(f"voice is off: tfm -s {name} voice start")
    text = " ".join(args.text).strip()
    if not text:
        raise TfmError("nothing to say")
    msg_id = state.queue_say(paths, text, interrupt=args.interrupt, also_text=args.text_chat)
    if not args.wait:
        print("Queued to speak.")
        return
    deadline = time.time() + 60
    while time.time() < deadline:
        done = state.was_said(paths, msg_id)
        if done:
            print(f"Speech failed: {done['error']}" if done.get("error") else "Spoken.")
            return
        time.sleep(0.3)
    print("Still queued after 60 s (the bot may be busy speaking).")


def cmd_listen(args):
    name = seat_name(args)
    paths = state.Paths(name)
    if args.last:
        for e in state.tail(paths, args.last):
            print(state.format_entry(e))
        return
    if not state.daemon_pid(paths) and not paths.heard.exists():
        raise TfmError(f"voice is off: tfm -s {name} voice start")
    deadline = time.time() + (args.wait or 0)
    entries = state.unread(paths)
    while not entries and time.time() < deadline:
        time.sleep(0.5)
        entries = state.unread(paths)
    entries = [e for e in entries if not (e.get("kind") == "said" and e.get("source") == "agent")]
    if not entries:
        print("Nothing new in voice chat.")
        return
    _print_block(entries, name, header="VOICE CHAT")


@_clean_errors
def cmd_test(args):
    """Check the speech engines without Discord: synthesize text, then transcribe it back."""
    from . import audio, stt, tts
    name = seat_name(args)
    paths = state.Paths(name).ensure()
    cfg = state.load_config(paths)
    text = " ".join(args.text) or "Hello table, I'll take the Tharsis Republic and an ocean for three megacredits."
    voice = tts.make(cfg)
    t0 = time.time()
    pcm = voice.synth(tts.speakable(text))
    out = paths.dir / "test.wav"
    out.write_bytes(audio.wav_bytes(pcm, audio.DISCORD_RATE, audio.DISCORD_CHANNELS))
    print(f"tts ({voice.name}): {audio.duration(pcm):.1f} s of audio in {time.time() - t0:.1f} s -> {out}")
    if args.play and sys.platform == "darwin":
        subprocess.run(["afplay", str(out)])
    if args.no_stt:
        return
    t0 = time.time()
    engine = stt.make(cfg)
    heard = engine.transcribe(audio.discord_to_speech(pcm))
    print(f"stt ({engine.name}): \"{heard}\" in {time.time() - t0:.1f} s")


def set_notes(name, text, append=False):
    paths = state.Paths(name).ensure()
    text = text.strip()
    if append and paths.notes.exists():
        text = paths.notes.read_text().rstrip() + "\n" + text
    paths.notes.write_text(text + "\n" if text else "")


def cmd_notes(args):
    name = seat_name(args)
    paths = state.Paths(name)
    if args.clear:
        set_notes(name, "")
        print("Notes cleared.")
    elif args.text:
        set_notes(name, " ".join(args.text), append=args.append)
        print("Notes saved for table talk.")
    else:
        print(responder.notes(paths) or "(no notes yet)")


@_clean_errors
def cmd_ask(args):
    """Run the table-talk responder here (live game state, notes, recent chat) and print its reply."""
    name = seat_name(args)
    paths = state.Paths(name).ensure()
    cfg = state.load_config(paths)
    r = responder.Responder(name, cfg, paths)
    t0 = time.time()
    summary = r.refresh()
    t1 = time.time()
    if args.show_context:
        print(summary, "\n")
    bot_name = (state.read_json(paths.status, {}) or {}).get("bot_name") or name
    kind, text = r.reply(args.speaker, " ".join(args.text), bot_name)
    print({"defer": "HANDED TO AGENT, says", "skip": "stays quiet (SKIP)"}.get(kind, "says") + f": {text}")
    print(f"(game state {t1 - t0:.1f} s, reply {time.time() - t1:.1f} s, {r.model}, {r.share})")


# ------------------------------------------------------------------ hooks used by tfm turn / state / play

def active(seat):
    """Voice paths for this seat if its daemon is running, else None. Never raises."""
    try:
        paths = state.Paths(seat)
        return paths if state.daemon_pid(paths) else None
    except Exception:
        return None


def addressed_pending(paths):
    """True if a person (not a bot) has said the seat's name in a line the agent hasn't seen."""
    try:
        return any(state.needs_agent(e) for e in state.unread(paths, advance=False))
    except Exception:
        return False


def _print_block(entries, seat, header="VOICE CHAT (since your last look)"):
    # Your own `voice say` lines are left out; auto-replies are shown so you know what "you" said.
    entries = [e for e in entries if not (e.get("kind") == "said" and e.get("source") == "agent")]
    if not entries:
        return
    print(f"{header}:")
    for e in entries:
        print("  " + state.format_entry(e))
    if any(state.needs_agent(e) for e in entries):
        print(f"YOU WERE ADDRESSED. Answer out loud: tfm -s {seat} voice say \"...\" "
              "(one or two short spoken sentences)")


def print_unread(seat, leading_blank=False, trailing_blank=True):
    """Print voice lines the agent hasn't seen yet. Returns the entries (empty if voice is off)."""
    paths = active(seat)
    if not paths:
        return []
    try:
        entries = state.unread(paths)
    except Exception:
        return []
    if any(not (e.get("kind") == "said" and e.get("source") == "agent") for e in entries):
        if leading_blank:
            print()
        _print_block(entries, seat)
        if trailing_blank:
            print()
    return entries


# ------------------------------------------------------------------ argparse wiring

def add_parser(sub):
    p = sub.add_parser("voice", help="join a Discord voice channel: hear the table and talk back")
    vs = p.add_subparsers(dest="voice_cmd", required=True)

    c = vs.add_parser("config", help="set the bot token, voice channel and speech engines (once per seat)")
    c.add_argument("--channel", help="voice channel link (right-click the channel > Copy Link)")
    c.add_argument("--token", help="Discord bot token (omit to be prompted, hidden)")
    c.add_argument("--stt", choices=["auto", "openai", "local"], help="speech to text (default auto)")
    c.add_argument("--tts", choices=["auto", "say", "openai"], help="text to speech (default auto: macOS say)")
    c.add_argument("--voice", help="voice name (`say -v '?'` lists macOS voices; OpenAI: alloy, nova, ...)")
    c.add_argument("--rate", type=int, help="speaking rate in words per minute (macOS say)")
    c.add_argument("--volume", type=float, help="playback volume, 1.0 = normal")
    c.add_argument("--whisper-model", dest="whisper_model", help="local model (default base.en; small.en is better)")
    c.add_argument("--language", help="spoken language code (default en)")
    c.add_argument("--openai-key", dest="openai_key", help="OpenAI API key (else $OPENAI_API_KEY)")
    c.add_argument("--silence-ms", dest="silence_ms", type=int, help="pause that ends an utterance (default 550)")
    c.add_argument("--responder", choices=["auto", "on", "off"],
                   help="fast table-talk auto-replies (default auto: on when an Anthropic key is set)")
    c.add_argument("--anthropic-key", dest="anthropic_key", help="Anthropic API key (else $ANTHROPIC_API_KEY)")
    c.add_argument("--responder-model", dest="responder_model", help="model for auto-replies (default claude-haiku-5-5)")
    c.add_argument("--share", choices=["private", "open"],
                   help="private (default): auto-replies never see your hand and keep plans hidden; open: talk freely")
    c.add_argument("--name", action="append", help="extra wake name, e.g. a nickname (repeatable)")
    c.add_argument("--clear-names", action="store_true", help="forget extra wake names")
    c.set_defaults(fn=cmd_config)

    s = vs.add_parser("start", help="start the voice daemon and join the channel")
    s.add_argument("--wait", type=int, default=90, help="seconds to wait for it to join (default 90)")
    s.add_argument("--debug", action="store_true", help="verbose daemon log")
    s.set_defaults(fn=cmd_start)

    vs.add_parser("stop", help="leave the channel and stop the daemon").set_defaults(fn=cmd_stop)
    vs.add_parser("status", help="is voice on, who is in the channel").set_defaults(fn=cmd_status)

    s = vs.add_parser("say", help="speak in the voice channel")
    s.add_argument("text", nargs="+")
    s.add_argument("--interrupt", action="store_true", help="cut off whatever is being said and drop the queue")
    s.add_argument("--text-chat", dest="text_chat", action="store_true",
                   help="also post it in the voice channel's text chat")
    s.add_argument("--wait", action="store_true", help="return only once it has been spoken")
    s.set_defaults(fn=cmd_say)

    s = vs.add_parser("listen", help="print what people said since you last looked")
    s.add_argument("--wait", type=int, default=0, help="wait up to S seconds for someone to speak")
    s.add_argument("--last", type=int, help="reprint the last N lines instead")
    s.set_defaults(fn=cmd_listen)

    s = vs.add_parser("notes", help="set the notes table talk answers from (no text: print them)")
    s.add_argument("text", nargs="*")
    s.add_argument("--append", action="store_true", help="add to the notes instead of replacing them")
    s.add_argument("--clear", action="store_true")
    s.set_defaults(fn=cmd_notes)

    s = vs.add_parser("ask", help="try a table-talk reply here, without Discord")
    s.add_argument("text", nargs="+")
    s.add_argument("--speaker", default="Ken", help="who is asking (default Ken)")
    s.add_argument("--show-context", dest="show_context", action="store_true", help="print the game state it sees")
    s.set_defaults(fn=cmd_ask)

    s = vs.add_parser("test", help="try the speech engines without Discord (speak a line, transcribe it back)")
    s.add_argument("text", nargs="*")
    s.add_argument("--play", action="store_true", help="also play it on this Mac's speakers")
    s.add_argument("--no-stt", dest="no_stt", action="store_true", help="only test text to speech")
    s.set_defaults(fn=cmd_test)
