"""Compact text summary of a player's view of the game."""
import time

from . import data
from .text import card_line, message

RES = [("megacredits", "MC"), ("steel", "St"), ("titanium", "Ti"), ("plants", "Pl"), ("energy", "En"), ("heat", "He")]
PROD = {"megacredits": "megacreditProduction", "steel": "steelProduction", "titanium": "titaniumProduction",
        "plants": "plantProduction", "energy": "energyProduction", "heat": "heatProduction"}


def resources(p):
    return "  ".join(f"{label} {p[k]}({p[PROD[k]]:+d})" for k, label in RES)


def tags(p):
    return ", ".join(f"{k} {v}" for k, v in sorted(p["tags"].items(), key=lambda kv: -kv[1]) if v) or "none"


def corporation(p):
    for card in p["tableau"]:
        info = data.card(card["name"])
        if info and info["type"] == "corporation":
            return card["name"]
    return "?"


def fmt_minutes(minutes):
    sign = "-" if minutes < 0 else ""
    total = int(abs(minutes) * 60)
    return f"{sign}{total // 60}:{total % 60:02d}"


def clock(p, options):
    """Elapsed time and Escape Velocity penalty projection, matching the server's formula."""
    timer = p["timer"]
    # The app does not time a player's first action of the game.
    running = timer["running"] and timer.get("afterFirstAction", True)
    elapsed_ms = timer["sumElapsed"] + (time.time() * 1000 - timer["startedAt"] if running else 0)
    elapsed = elapsed_ms / 60000
    ev = options.get("escapeVelocity")
    if not ev:
        return f"clock {fmt_minutes(elapsed)}"
    allowance = ev["thresholdMinutes"] + p["actionsTakenThisGame"] * ev["bonusSectionsPerAction"] / 60
    over = elapsed - allowance
    if over <= 0:
        return f"clock {fmt_minutes(elapsed)} of {fmt_minutes(allowance)} allowance ({fmt_minutes(-over)} left before the time penalty)"
    period = ev["penaltyPeriodMinutes"]
    penalty = ev["penaltyVPPerPeriod"] * int(over // period)
    to_next = period - (over % period)
    return f"clock {fmt_minutes(elapsed)}, {fmt_minutes(over)} over allowance: penalty now -{penalty} VP (next -{ev['penaltyVPPerPeriod']} in {fmt_minutes(to_next)})"


def globals_line(g):
    parts = [
        f"temp {g['temperature']}°C/+8 ({max(0, (8 - g['temperature']) // 2)} steps left)",
        f"O2 {g['oxygenLevel']}%/14 ({max(0, 14 - g['oxygenLevel'])} left)",
        f"oceans {g['oceans']}/9 ({max(0, 9 - g['oceans'])} left)",
    ]
    if g["gameOptions"]["expansions"].get("venus"):
        parts.append(f"Venus {g['venusScaleLevel']}%/30")
    return " · ".join(parts)


def milestones(g, me, names, ctx):
    ms = g["milestones"]
    claimed = [m for m in ms if m.get("playerName")]
    lines = [f"MILESTONES ({len(claimed)}/3 claimed, cost 8 MC):"]
    for m in ms:
        scores = {s["color"]: s for s in m["scores"]}
        mine = scores.get(me["color"], {})
        rivals = sorted((s for c, s in scores.items() if c != me["color"]), key=lambda s: -s["score"])
        best = rivals[0] if rivals else None
        desc = data.milestone_text(m["name"]) if ctx.show_text("ms:" + m["name"]) else None
        line = f"  {m['name']}"
        if desc:
            line += f" ({desc})"
        if m.get("playerName"):
            line += f": CLAIMED by {m['playerName']}"
        else:
            line += f": you {mine.get('score', '?')}"
            if best:
                line += f", best rival {names.get(best['color'], best['color'])} {best['score']}"
            claimable = [names.get(c, c) for c, s in scores.items() if s.get("claimable")]
            if mine.get("claimable"):
                line += "  <<< YOU CAN CLAIM"
            elif claimable:
                line += f"  (claimable by {', '.join(claimable)})"
        lines.append(line)
    return lines


def awards(g, me, names, ctx):
    aw = g["awards"]
    funded = [a for a in aw if a.get("playerName")]
    cost = [8, 14, 20][len(funded)] if len(funded) < 3 else None
    head = f"AWARDS ({len(funded)}/3 funded" + (f", next costs {cost} MC):" if cost else "):")
    lines = [head]
    for a in aw:
        if len(funded) == 3 and not a.get("playerName"):
            continue
        ranked = sorted(a["scores"], key=lambda s: -s["score"])
        desc = data.award_text(a["name"]) if ctx.show_text("aw:" + a["name"]) else None
        line = f"  {a['name']}" + (f" ({desc})" if desc else "")
        line += f" [funded by {a['playerName']}]" if a.get("playerName") else " [not funded]"
        line += ": " + ", ".join(
            ("YOU" if s["color"] == me["color"] else names.get(s["color"], s["color"])) + f" {s['score']}" for s in ranked)
        lines.append(line)
    return lines


def colonies(g, view, names):
    active = [c for c in g["colonies"] if c.get("isActive", True)]
    if not active:
        return []
    me = view["thisPlayer"]
    lines = [f"COLONIES (your fleets {me['fleetSize']}, trades used {me['tradesThisGeneration']}; you own {me['coloniesCount']}):"]
    for c in active:
        info = data.colony(c["name"]) or {}
        qty = info.get("tradeQty")
        pos = c.get("trackPosition", 0)
        now = qty[pos] if isinstance(qty, list) and pos < len(qty) else "?"
        owners = ", ".join(names.get(x, x) for x in c["colonies"]) or "-"
        line = f"  {c['name']}: trade {info.get('trade', '?')} (n={now} now) · colonies {owners} ({len(c['colonies'])}/3)"
        if c.get("visitor"):
            line += f" · fleet: {names.get(c['visitor'], c['visitor'])}"
        lines.append(line)
    return lines


def tableau(p):
    out = []
    for card in p["tableau"]:
        info = data.card(card["name"]) or {}
        if info.get("type") == "corporation":
            continue
        s = card["name"]
        if card.get("resources"):
            s += f"[{card['resources']}]"
        out.append(s)
    return ", ".join(out) or "none"


def summarize(view, ctx, new_logs):
    g = view["game"]
    me = view["thisPlayer"]
    names = ctx.names
    opts = g["gameOptions"]
    out = []
    out.append(f"GAME {g['name']} · generation {g['generation']} · phase {g['phase']} · map {opts['boardName']}"
               f" · {len(view['players'])} players")
    out.append("GLOBALS: " + globals_line(g))
    if g.get("pathfinders"):
        tracks = ", ".join(f"{k} {v}" for k, v in g["pathfinders"].items() if v is not None and v >= 0)
        out.append(f"PLANETARY TRACKS: {tracks}")
    vp = me["victoryPointsBreakdown"]
    out.append("")
    out.append(f"YOU: {me['name']} ({me['color']}) · {corporation(me)} · TR {me['terraformRating']} · "
               f"VP now {vp['total']} (TR {vp['terraformRating']}, milestones {vp['milestones']}, awards {vp['awards']}, "
               f"greenery {vp['greenery']}, city {vp['city']}, cards {vp['victoryPoints']})")
    out.append(f"  {resources(me)}  · steel={me['steelValue']} ti={me['titaniumValue']}")
    out.append(f"  tags: {tags(me)}")
    out.append(f"  tiles: {me['citiesCount']} cities · colonies {me['coloniesCount']} · "
               f"corruption {me.get('underworldData', {}).get('corruption', 0)}")
    out.append(f"  played: {tableau(me)}")
    if me["actionsThisGeneration"]:
        out.append(f"  card actions used this generation: {', '.join(me['actionsThisGeneration'])}")
    out.append(f"  {clock(me, opts)} · actions taken {me['actionsTakenThisGame']}")
    hand = view.get("cardsInHand", [])
    out.append(f"  HAND ({len(hand)}):")
    for c in hand:
        out.append("    " + card_line(c, with_text=ctx.show_text(c["name"])))
    for label, key in (("PRELUDES IN HAND", "preludeCardsInHand"), ("DRAFTED", "draftedCards")):
        cards = view.get(key) or []
        if cards:
            out.append(f"  {label}: " + "; ".join(card_line(c, with_text=ctx.show_text(c["name"])) for c in cards))

    out.append("")
    out.append("OPPONENTS:")
    passed = set(g.get("passedPlayers", []))
    for p in view["players"]:
        if p["color"] == me["color"]:
            continue
        flag = " PASSED" if p["color"] in passed else (" (acting)" if p.get("isActive") else "")
        out.append(f"  {p['name']} ({p['color']}) · {corporation(p)} · TR {p['terraformRating']} · hand {p['cardsInHandNbr']}"
                   f" · cities {p['citiesCount']} · colonies {p['coloniesCount']}{flag}")
        out.append(f"    {resources(p)}")
        out.append(f"    tags: {tags(p)}")
        out.append(f"    played: {tableau(p)}")

    out.append("")
    out.extend(milestones(g, me, names, ctx))
    out.extend(awards(g, me, names, ctx))
    out.extend(colonies(g, view, names))

    if new_logs:
        out.append("")
        out.append("SINCE YOUR LAST LOOK:")
        for entry in new_logs[-60:]:
            out.append("  " + message(entry, names))
    return out


def final_scores(view):
    lines = ["GAME OVER. Final scores:"]
    for p in sorted(view["players"], key=lambda p: -p["victoryPointsBreakdown"]["total"]):
        vp = p["victoryPointsBreakdown"]
        lines.append(f"  {p['name']}: {vp['total']} (TR {vp['terraformRating']}, milestones {vp['milestones']}, awards {vp['awards']},"
                     f" greenery {vp['greenery']}, city {vp['city']}, cards {vp['victoryPoints']}, time {vp['escapeVelocity']})")
    return lines
