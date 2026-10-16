"""Estimate every player's VP from public information, as the app would score it if the game ended now.

The app hides other players' VP breakdowns unless the game shows them, so this recomputes them from what
everyone can see: TR, claimed milestones, funded awards' standings, tiles on the board and played cards.
Card VP the bundled data can't compute (custom card rules, VP from neighbouring tiles) is listed by name.
"""
import re

from . import data

CITY_TILES = {"city", "Capital", "Ocean City", "Red City", "New Holland"}
GREENERY_TILES = {"greenery", "Wetlands"}
OCEAN_TILES = {"ocean", "Ocean City", "Ocean Farm", "Ocean Sanctuary", "Wetlands", "New Holland"}


def _tile(space):
    return data.tile_name(space["tileType"]) if space.get("tileType") is not None else None


def award_points(game, color):
    """5 for first (shared on a tie), 2 for second when first is not tied; as the app scores funded awards."""
    total = 0
    for award in game["awards"]:
        if not award.get("playerName"):
            continue
        scores = sorted((s["score"] for s in award["scores"]), reverse=True)
        mine = next((s["score"] for s in award["scores"] if s["color"] == color), None)
        if mine is None or not scores:
            continue
        if mine == scores[0]:
            total += 5
        elif scores.count(scores[0]) == 1 and len(scores) > 2 and mine == scores[1]:
            total += 2
    return total


def board_points(game, board_name, color):
    """(greenery, city) points from the tiles a player owns."""
    spaces = {s["id"]: s for s in game["spaces"]}
    greenery = city = 0
    for s in game["spaces"]:
        if s.get("color") != color:
            continue
        tile = _tile(s)
        if tile in GREENERY_TILES:
            greenery += 1
        elif tile in CITY_TILES:
            city += sum(1 for a in data.adjacency(board_name, s["id"]) if _tile(spaces.get(a, {})) in GREENERY_TILES)
    return greenery, city


def _next_to_own_tile(game, color, card_name, kinds):
    """Tiles of `kinds` next to the player's tile named after the card (e.g. Commercial District), or None."""
    tile_name = card_name.split(":")[0]
    spaces = {s["id"]: s for s in game["spaces"]}
    board_name = game["gameOptions"]["boardName"]
    for s in game["spaces"]:
        if s.get("color") == color and _tile(s) == tile_name:
            return sum(1 for a in data.adjacency(board_name, s["id"]) if _tile(spaces.get(a, {})) in kinds)
    return None


def card_points(player, game):
    """(points, cards whose VP could not be computed) for a player's played cards."""
    points, unknown, negative = 0, [], 0
    cities_on_mars = sum(1 for s in game["spaces"] if _tile(s) in CITY_TILES and s.get("spaceType") != "colony")
    colonies_in_play = sum(len(c.get("colonies", [])) for c in game.get("colonies") or [])
    for card in player["tableau"]:
        vp = (data.behavior(card["name"]) or {}).get("vp")
        if vp is None:
            continue
        if isinstance(vp, (int, float)):
            got = vp
        elif isinstance(vp, dict) and "resourcesHere" in vp:
            n = card.get("resources") or 0
            got = n * vp["each"] if "each" in vp else n // vp.get("per", 1)
        elif isinstance(vp, dict) and "tag" in vp and len(vp) <= 2:
            got = player["tags"].get(vp["tag"], 0) // vp.get("per", 1)
        elif isinstance(vp, dict) and "cities" in vp and vp.get("all"):
            got = cities_on_mars // vp.get("per", 1)
        elif isinstance(vp, dict) and "colonies" in vp and vp.get("all"):
            got = colonies_in_play // vp.get("per", 1)
        elif isinstance(vp, dict) and "nextToThis" in vp and ("cities" in vp or "oceans" in vp):
            got = _next_to_own_tile(game, player["color"], card["name"], CITY_TILES if "cities" in vp else OCEAN_TILES)
            if got is None:
                unknown.append(card["name"])
                continue
        else:
            unknown.append(card["name"])
            continue
        points += got
        negative += min(got, 0)
    return points, unknown, negative


def colony_build_points(game, color):
    """VP from building colonies on tiles whose build reward is VP by order placed (Titania: 5, 3, 2)."""
    total = 0
    for col in game.get("colonies") or []:
        m = re.match(r"Gain ([\d, or]+) VP", (data.colony(col["name"]) or {}).get("build", ""))
        if not m:
            continue
        rewards = [int(x) for x in re.findall(r"\d+", m.group(1))]
        total += sum(rewards[i] for i, owner in enumerate(col.get("colonies", [])) if owner == color and i < len(rewards))
    return total


def estimate(view, player):
    """VP breakdown for one player, computed from public information only."""
    g = view["game"]
    color = player["color"]
    greenery, city = board_points(g, g["gameOptions"]["boardName"], color)
    cards, unknown, negative = card_points(player, g)
    cards += colony_build_points(g, color)
    if g["gameOptions"]["expansions"].get("underworld"):
        cards += min(-negative, (player.get("underworldData") or {}).get("corruption", 0))
    parts = {
        "terraformRating": player["terraformRating"],
        "milestones": 5 * sum(1 for m in g["milestones"] if m.get("playerName") == player["name"]),
        "awards": award_points(g, color),
        "greenery": greenery,
        "city": city,
        "victoryPoints": cards,
    }
    parts["total"] = sum(parts.values())
    return parts, unknown


def vp_trade_colonies(game):
    """Names of colonies in play whose trade reward is VP (Titania)."""
    return {c["name"] for c in game.get("colonies") or [] if "VP" in (data.colony(c["name"]) or {}).get("trade", "")}


def count_vp_trades(game, logs):
    """color -> number of trades with VP-giving colonies, from the game log."""
    names = vp_trade_colonies(game)
    counts = {}
    for entry in logs:
        if "trade with" not in entry.get("message", ""):
            continue
        values = [d.get("value") for d in entry.get("data", [])]
        if values and any(v in names for v in values):
            counts[values[0]] = counts.get(values[0], 0) + 1
    return counts


def report(view, vp_trades=None):
    """Lines for `tfm vp`: every player's estimate, best first, with your exact score from the app."""
    me = view["thisPlayer"]
    rows = []
    for p in view["players"]:
        parts, unknown = estimate(view, p)
        if p["color"] == me["color"]:
            exact = me["victoryPointsBreakdown"]
            parts = {k: exact[k] for k in parts}  # the app's own numbers for you
            unknown = []
        rows.append((p, parts, unknown))
    rows.sort(key=lambda r: -r[1]["total"])
    out = ["VP IF THE GAME ENDED NOW (awards by current standings; rivals estimated from public info):"]
    for p, v, unknown in rows:
        who = "YOU" if p["color"] == me["color"] else p["name"]
        approx = "" if p["color"] == me["color"] else "~"
        line = (f"  {who}: {approx}{v['total']} = TR {v['terraformRating']} + milestones {v['milestones']} + "
                f"awards {v['awards']} + greenery {v['greenery']} + city {v['city']} + cards {approx}{v['victoryPoints']}")
        if unknown:
            line += f" (+? from {', '.join(unknown)}: run `tfm card`)"
        trades = (vp_trades or {}).get(p["color"], 0)
        if trades and p["color"] != me["color"]:
            line += f" (+? from {trades} trade(s) with {', '.join(sorted(vp_trade_colonies(view['game'])))}: 0-2 VP each)"
        out.append(line)
    out.append("  Not counted for rivals: planetary-track and Moon VP, and the time penalty.")
    return out
