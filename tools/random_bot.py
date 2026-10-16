"""Stress test: play every seat of a game with random legal choices through the tfm CLI.

Usage:
    python3 tools/random_bot.py SEAT [SEAT ...] [--steps 3000]

Each seat must already be joined (`tfm join ... --as NAME`). Use a local server: the bots make
thousands of requests. Rejections and crashes are printed so they can be fixed.
"""
import argparse
import contextlib
import io
import random
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tfm import cli, options, seats  # noqa: E402
from tfm.client import Client  # noqa: E402


def gen_value(node, ctx):
    t = node["type"]
    if t == "card":
        names = [c["name"] for c in node["cards"] if not c.get("isDisabled")]
        lo, hi = node.get("min", 0), node.get("max", len(names))
        k = random.randint(lo, max(lo, min(hi, lo + 2)))
        return ",".join(random.sample(names, min(k, len(names)))) or "none"
    if t == "amount":
        return str(random.randint(node["min"], node["max"]))
    if t == "resources":
        return f"plants={node['count']}"
    if t == "productionToLose":
        me = ctx.me
        need, out = node["payProduction"]["cost"], []
        room = {"megacredits": me["megacreditProduction"] + 5, "steel": me["steelProduction"],
                "titanium": me["titaniumProduction"], "plants": me["plantProduction"],
                "energy": me["energyProduction"], "heat": me["heatProduction"]}
        for k, v in room.items():
            take = min(v, need)
            if take > 0:
                out.append(f"{k}={take}")
                need -= take
        return ",".join(out) or "none"
    if t == "claimedUndergroundToken":
        return ",".join(str(i) for i in range(node["min"])) or ""
    if t == "aresGlobalParameters":
        return "lowOceanDelta=0,highOceanDelta=0,temperatureDelta=0,oxygenDelta=0"
    if t == "space":
        return random.choice(node["spaces"])
    if t == "player":
        return ctx.names.get(node["players"][0], node["players"][0])
    if t == "colony":
        return node["coloniesModel"][0]["name"]
    if t == "resource":
        return node["include"][0]
    return None


def values_for(leaf, ctx):
    node = leaf.node
    if leaf.fixed is not None or node["type"] in ("option", "payment", "projectCard"):
        return []
    if node["type"] == "and" and options._all_amounts(node):
        nums = re.findall(r"\d+", options._title(node, ctx))
        first = node["options"][0]
        return [f"{options._title(first, ctx)}={min(int(nums[0]) if nums else 0, first['max'])}"]
    if node["type"] in ("and", "initialCards"):
        return [gen_value(o, ctx) or "" for o in node["options"]]
    v = gen_value(node, ctx)
    return [] if v is None else [v]


def weight(leaf):
    label = leaf.label.lower()
    if "undo" in label:
        return 0
    if "pass for this generation" in label:
        return 1
    if "can't afford" in label:
        return 0
    if "end turn" in label or "skip" in label or "do nothing" in label:
        return 2
    return 10


def run(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("seats", nargs="+")
    parser.add_argument("--steps", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    random.seed(args.seed)
    problems = 0
    for step in range(args.steps):
        acted = False
        for name in args.seats:
            seat = seats.load(name)
            view = Client(seat["server"], seat["player_id"]).player()
            if view["game"]["phase"] == "end":
                print(f"game over after {step} rounds")
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    cli.main(["--seat", name, "state"])
                print(buf.getvalue())
                return problems
            wf = view.get("waitingFor")
            if wf is None or wf.get("optional"):
                continue
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    cli.main(["--seat", name, "state"])  # exercises the digest + option listing
            except SystemExit:
                pass
            except Exception:
                problems += 1
                print(f"CRASH in state for {name}:\n{traceback.format_exc()}")
            seat = seats.load(name)
            ctx = options.Context(view, set(), False)
            leaves = options.leaves(wf, ctx)
            for _attempt in range(8):
                pool = [lf for lf in leaves if weight(lf) > 0] or leaves
                leaf = random.choices(pool, weights=[weight(lf) or 1 for lf in pool])[0]
                vals = values_for(leaf, ctx)
                buf = io.StringIO()
                code = 0
                try:
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        cli.main(["--seat", name, "play", leaf.id, *vals])
                except SystemExit as e:
                    code = e.code or 0
                except Exception:
                    problems += 1
                    print(f"CRASH in play {leaf.id} {vals} for {name} ({wf['type']}):\n{traceback.format_exc()}")
                    code = 99
                out = buf.getvalue()
                if code == 0:
                    acted = True
                    break
                if "REJECTED" in out or "ERROR" in out:
                    first = next((ln for ln in out.splitlines() if "REJECTED" in ln or "ERROR" in ln), out[:200])
                    print(f"[{name}] rejected {leaf.id} '{leaf.label[:70]}' {vals}: {first[:200]}")
                if code == 2:  # options changed; refresh
                    break
        if not acted:
            print("nobody could act; stopping")
            return problems
    print("step limit reached")
    return problems


if __name__ == "__main__":
    sys.exit(1 if run(sys.argv[1:]) else 0)
