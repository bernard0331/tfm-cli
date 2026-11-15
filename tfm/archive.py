"""Save finished games to disk, so their results outlive the server's copy.

The server deletes a finished game some days after it ends. `tfm archive` keeps what a seat can
see at the end: its final player view (settings, every player's corporation, played cards, tags
and VP breakdown) and the log of every generation. One file per game:

    $TFM_HOME/games/<game-name>-<key>.json      (TFM_HOME defaults to ~/.tfm)

Only the seat's own player link is used. Several seats in the same game share one file: each adds
its own view, and the logs are merged.
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path

from . import seats
from .client import Client, TfmError

FORMAT = 1
# Player and spectator ids are the secret part of a game link. At the end of a game the server
# includes every player's id in the view, so they are blanked before anything is written.
_ID = re.compile(r"^[ps][0-9a-f]{10,}$")
REDACTED = "redacted"


def home():
    path = Path(os.environ.get("TFM_HOME", Path.home() / ".tfm")) / "games"
    path.mkdir(parents=True, exist_ok=True)
    return path


def game_key(view):
    """A stable id for the game that is the same for every seat in it and reveals no link."""
    return hashlib.sha256(view["game"]["spectatorId"].encode()).hexdigest()[:12]


def path_for(view):
    return home() / f"{seats.slug(view['game']['name'])}-{game_key(view)}.json"


def redact(obj):
    """A copy of obj with every player or spectator id replaced."""
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str) and _ID.match(obj):
        return REDACTED
    return obj


def _merge_logs(old, new):
    """Union of two lists of log entries, oldest first. Seats see different private entries."""
    seen, merged = set(), []
    for entry in list(old) + list(new):
        fingerprint = json.dumps(entry, sort_keys=True)
        if fingerprint not in seen:
            seen.add(fingerprint)
            merged.append(entry)
    return sorted(merged, key=lambda e: e.get("timestamp", 0))


def _read(path):
    try:
        record = json.loads(path.read_text())
    except ValueError:
        raise TfmError(f"{path} exists but is not valid JSON; move it away and archive again") from None
    if record.get("format") != FORMAT:
        raise TfmError(f"{path} has archive format {record.get('format')}, this tfm writes format {FORMAT}")
    return record


def _write(path, record):
    """Write through a temporary file, so a crash never leaves a half-written archive."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, indent=1))
    os.replace(tmp, path)


def is_archived(view):
    """True if this seat's view of this game is already saved."""
    path = path_for(view)
    if not path.exists():
        return False
    try:
        return view["thisPlayer"]["color"] in _read(path)["views"]
    except TfmError:
        return False


def save(client, seat, view=None):
    """Archive the seat's finished game. Returns (path, True if the file is new)."""
    view = view or client.player()
    game = view["game"]
    if game["phase"] != "end":
        raise TfmError(f"game '{game['name']}' is not finished (generation {game['generation']}, "
                       f"phase {game['phase']}); archive it when it ends")
    logs = {str(g): redact(client.logs(g) or []) for g in range(1, game["generation"] + 1)}
    path = path_for(view)
    created = not path.exists()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record = {"format": FORMAT, "game_key": game_key(view), "game_name": game["name"], "server": seat["server"],
              "generations": game["generation"], "first_archived_at": now, "views": {}, "logs": {}}
    if not created:
        record = _read(path)
    record["archived_at"] = now
    record["views"][view["thisPlayer"]["color"]] = {"seat": seat["name"], "archived_at": now, "view": redact(view)}
    for gen, entries in logs.items():
        record["logs"][gen] = _merge_logs(record["logs"].get(gen, []), entries)
    _write(path, record)
    return path, created


def save_all():
    """Backfill: try every saved seat. Returns [(seat name, game name, outcome, detail)]."""
    results = []
    for name in seats.names():
        seat = seats.load(name)
        try:
            path, created = save(Client(seat["server"], seat["player_id"]), seat)
            results.append((name, seat.get("game"), "archived" if created else "updated", str(path)))
        except TfmError as e:
            outcome = "not finished" if "is not finished" in str(e) else "failed"
            if "(404)" in str(e) or "not found" in str(e).lower():
                e = "the server no longer has this game; it cannot be recovered"
            results.append((name, seat.get("game"), outcome, str(e)))
    return results
