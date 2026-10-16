"""Per-seat local state: which game a seat plays and what it has already seen."""
import json
import os
import re
from pathlib import Path

from .client import TfmError


def home():
    path = Path(os.environ.get("TFM_HOME", Path.home() / ".tfm")) / "seats"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(name):
    return home() / f"{name}.json"


def slug(name):
    return re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "seat"


def save(seat):
    _path(seat["name"]).write_text(json.dumps(seat, indent=1))


def names():
    return sorted(p.stem for p in home().glob("*.json"))


def load(name=None):
    """Load a seat by name, then $TFM_SEAT, then the only saved seat."""
    name = name or os.environ.get("TFM_SEAT")
    if name is None:
        available = names()
        if len(available) == 1:
            name = available[0]
        elif not available:
            raise TfmError("no seat joined yet: run `tfm join <player-link>`")
        else:
            raise TfmError(f"several seats saved ({', '.join(available)}): pass --seat NAME or set TFM_SEAT")
    path = _path(slug(name))
    if not path.exists():
        raise TfmError(f"unknown seat '{name}'. Known: {', '.join(names()) or 'none'}")
    return json.loads(path.read_text())


def remove(name):
    _path(slug(name)).unlink(missing_ok=True)
