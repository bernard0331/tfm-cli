"""On-disk state shared by the `tfm voice` commands and the voice daemon (standard library only).

Everything for one seat lives in ~/.tfm/voice/<seat>/ (TFM_HOME overrides ~/.tfm):

    config.json    bot token, channel, speech engines, wake names (chmod 600)
    status.json    written by the daemon: state, channel, who is in it, last error
    daemon.pid     pid of the running daemon
    heard.jsonl    what people said (one JSON object per line), appended by the daemon
    heard.cursor   byte offset of the first line the agent has not been shown yet
    said.jsonl     delivery receipts for `voice say` (heard.jsonl also records everything the bot says)
    notes.md       the agent's notes for the table-talk responder
    outbox/        queued `voice say` requests, one JSON file each, spoken in name order
    bot.log        daemon log
"""
import json
import os
import re
import signal
import time
from pathlib import Path

from ..client import TfmError

DEFAULTS = {
    "token": None,          # Discord bot token (falls back to $DISCORD_BOT_TOKEN)
    "guild_id": None,
    "channel_id": None,
    "stt": "auto",          # auto | openai | local
    "tts": "auto",          # auto | say | openai
    "voice": None,          # `say -v` voice, or OpenAI voice name
    "rate": None,           # `say -r` words per minute
    "volume": 1.0,
    "names": [],            # extra wake names (STT spellings of the seat name, nicknames)
    "followup_s": 20,       # after the bot speaks, lines this many seconds later count as addressed to it
    "language": "en",
    "whisper_model": "base.en",           # local faster-whisper model
    "openai_stt_model": "gpt-4o-mini-transcribe",
    "openai_tts_model": "gpt-4o-mini-tts",
    "openai_key": None,     # falls back to $OPENAI_API_KEY
    "silence_ms": 550,      # a pause this long ends an utterance
    "min_speech_ms": 400,   # shorter utterances are ignored (coughs, clicks)
    "max_utterance_s": 30,
    "responder": "auto",    # table-talk auto-replies: auto (on when an Anthropic key is set) | on | off
    "responder_model": "claude-haiku-5-5",
    "anthropic_key": None,  # falls back to $ANTHROPIC_API_KEY
    "share": "private",     # private: hand and plans stay hidden | open: talk about everything
}

# Common speech-to-text spellings of seat names, so "hey cloud" still reaches the claude seat.
SOUNDALIKES = {
    "claude": ["claude", "claud", "clod", "cloud", "clawed", "klaud"],
    "gpt": ["gpt", "g p t", "chat gpt", "chatgpt"],
    "codex": ["codex", "code x"],
    "gemini": ["gemini"],
}


def root():
    return Path(os.environ.get("TFM_HOME", Path.home() / ".tfm")) / "voice"


def slug(name):
    return re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "seat"


class Paths:
    def __init__(self, seat):
        self.seat = slug(seat)
        self.dir = root() / self.seat
        self.config = self.dir / "config.json"
        self.status = self.dir / "status.json"
        self.pid = self.dir / "daemon.pid"
        self.heard = self.dir / "heard.jsonl"
        self.cursor = self.dir / "heard.cursor"
        self.said = self.dir / "said.jsonl"
        self.outbox = self.dir / "outbox"
        self.log = self.dir / "bot.log"
        self.notes = self.dir / "notes.md"

    def ensure(self):
        self.outbox.mkdir(parents=True, exist_ok=True)
        return self


def configured_seats():
    if not root().exists():
        return []
    return sorted(p.name for p in root().iterdir() if (p / "config.json").exists())


# ---------------------------------------------------------------- json helpers

def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, obj, private=False):
    """Write atomically, so a reader never sees half a file."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=1))
    if private:
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def append_jsonl(path, obj):
    with open(path, "a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- config

def load_config(paths):
    cfg = dict(DEFAULTS)
    cfg.update(read_json(paths.config, {}) or {})
    return cfg


def save_config(paths, cfg):
    paths.ensure()
    write_json(paths.config, {k: v for k, v in cfg.items() if v != DEFAULTS.get(k, object())}, private=True)


def token(cfg):
    return cfg.get("token") or os.environ.get("DISCORD_BOT_TOKEN")


def openai_key(cfg):
    return cfg.get("openai_key") or os.environ.get("OPENAI_API_KEY")


def parse_channel(text):
    """Accept a channel link (https://discord.com/channels/<guild>/<channel>) or '<guild>/<channel>'."""
    m = re.search(r"(\d{15,25})/(\d{15,25})/?\s*$", text.strip())
    if not m:
        raise TfmError("give the voice channel as its link: right-click the channel in Discord > Copy Link "
                       "(https://discord.com/channels/<server id>/<channel id>)")
    return int(m.group(1)), int(m.group(2))


def wake_names(seat, cfg, status=None):
    names = {slug(seat).replace("-", " ")}
    names.update(SOUNDALIKES.get(slug(seat), []))
    names.update(n.lower() for n in cfg.get("names") or [])
    bot = (status or {}).get("bot_name")
    if bot:
        names.add(bot.lower())
    return sorted(n for n in names if n)


def is_addressed(text, names):
    low = " " + re.sub(r"[^a-z0-9 ]+", " ", text.lower()) + " "
    low = re.sub(r"\s+", " ", low)
    return any(f" {re.sub(r'[^a-z0-9 ]+', ' ', n).strip()} " in low for n in names)


# ---------------------------------------------------------------- daemon process

def daemon_pid(paths):
    """The daemon's pid if it is running, else None (and stale pid files are removed)."""
    try:
        pid = int(paths.pid.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        try:
            paths.pid.unlink()
        except OSError:
            pass
        return None
    except PermissionError:
        pass
    return pid


def stop_daemon(paths, timeout=10):
    pid = daemon_pid(paths)
    if pid is None:
        return False
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + timeout
    while time.time() < deadline and daemon_pid(paths) == pid:
        time.sleep(0.2)
    if daemon_pid(paths) == pid:
        os.kill(pid, signal.SIGKILL)
        try:
            paths.pid.unlink()
        except OSError:
            pass
    return True


# ---------------------------------------------------------------- heard log

def unread(paths, advance=True):
    """Entries the agent has not been shown yet."""
    if not paths.heard.exists():
        return []
    try:
        offset = int(paths.cursor.read_text().strip())
    except (OSError, ValueError):
        offset = 0
    size = paths.heard.stat().st_size
    if offset > size:  # log was reset
        offset = 0
    with open(paths.heard, "rb") as f:
        f.seek(offset)
        chunk = f.read()
    # Only consume complete lines; the daemon may be mid-write.
    end = chunk.rfind(b"\n") + 1
    entries = []
    for line in chunk[:end].splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    if advance and end:
        paths.cursor.write_text(str(offset + end))
    return entries


def tail(paths, n):
    if not paths.heard.exists():
        return []
    lines = paths.heard.read_text(errors="replace").splitlines()[-n:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def skip_to_end(paths):
    if paths.heard.exists():
        paths.cursor.write_text(str(paths.heard.stat().st_size))


def format_entry(e):
    ts = time.strftime("%H:%M:%S", time.localtime(e.get("ts", 0)))
    who = e.get("speaker", "?")
    kind = e.get("kind", "voice")
    if kind == "join":
        return f"[{ts}] {who} joined the voice channel"
    if kind == "leave":
        return f"[{ts}] {who} left the voice channel"
    if kind == "said":
        return f"[{ts}] YOU (table-talk auto-reply): {e.get('text', '')}"
    if kind == "handoff":
        return f"[{ts}] {who} asked you (needs YOUR answer): {e.get('text', '')}"
    tag = " (bot)" if e.get("bot") else ""
    return f"[{ts}] {who}{tag}: {e.get('text', '')}"


def needs_agent(e):
    """A line the playing agent should answer: a person said its name and the auto-responder isn't handling it,
    or the responder handed the question over."""
    if e.get("kind") == "handoff":
        return True
    return e.get("kind") == "voice" and e.get("addressed") and not e.get("bot") and not e.get("auto")


# ---------------------------------------------------------------- outbox

def queue_say(paths, text, interrupt=False, also_text=False):
    paths.ensure()
    msg_id = f"{time.time_ns()}-{os.getpid()}"
    write_json(paths.outbox / f"{msg_id}.json",
               {"id": msg_id, "text": text, "interrupt": interrupt, "also_text": also_text, "ts": time.time()})
    return msg_id


def take_outbox(paths):
    """Pop queued messages in order (daemon side)."""
    out = []
    for f in sorted(paths.outbox.glob("*.json")):
        msg = read_json(f)
        try:
            f.unlink()
        except OSError:
            continue
        if msg and msg.get("text"):
            out.append(msg)
    return out


def was_said(paths, msg_id):
    if not paths.said.exists():
        return None
    for line in reversed(paths.said.read_text(errors="replace").splitlines()[-200:]):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("id") == msg_id:
            return e
    return None
