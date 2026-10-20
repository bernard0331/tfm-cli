"""Formatting helpers shared by the digest and option listing."""
import re

from . import data

# LogMessageDataType values from the app.
_PLAYER, _CARD, _TILE, _BONUS, _CARDS = 2, 3, 9, 10, 14


def message(msg, names=None):
    """Render an app Message ({message, data} or plain string) as text."""
    if msg is None:
        return ""
    if isinstance(msg, str):
        return msg
    names = names or {}
    values = []
    for d in msg.get("data", []):
        t, v = d.get("type"), d.get("value")
        if t == _PLAYER:
            values.append(names.get(v, v))
        elif t == _TILE:
            values.append(data.tile_name(v))
        elif t == _BONUS:
            values.append(data.bonus_name(v))
        elif t == _CARDS:
            values.append(", ".join(v))
        else:
            values.append(str(v))

    def sub(m):
        i = int(m.group(1))
        return values[i] if i < len(values) else m.group(0)

    return re.sub(r"\$\{(\d+)\}", sub, msg.get("message", ""))


def card_line(model_or_name, with_text=True, cost=None):
    """One line describing a card: name, cost, tags, requirements, VP, text."""
    if isinstance(model_or_name, dict):
        name = model_or_name["name"]
        cost = model_or_name.get("calculatedCost", cost)
        resources = model_or_name.get("resources")
    else:
        name, resources = model_or_name, None
    info = data.card(name) or {}
    bits = []
    if cost is None:
        cost = info.get("cost")
    if info.get("type") not in ("corporation", "prelude", "ceo") and cost is not None:
        bits.append(f"{cost}MC")
    if info.get("tags"):
        bits.append("/".join(info["tags"]))
    if info.get("type") == "event":
        bits.append("event")
    if info.get("req"):
        bits.append("req " + ", ".join(info["req"]))
    if info.get("vp"):
        bits.append(f"VP {info['vp']}")
    if resources:
        bits.append(f"{resources} {info.get('resource', 'res')}")
    line = name + (f" ({'; '.join(bits)})" if bits else "")
    if with_text and info.get("text"):
        line += f" — {data.card_text(name)}"
    return line


def units(u):
    short = {"megacredits": "MC", "steel": "St", "titanium": "Ti", "plants": "Pl", "energy": "En", "heat": "He"}
    return " ".join(f"{v} {short.get(k, k)}" for k, v in u.items() if v)
