"""Record a random-bot game the way an agent sees it, for offline comparison of output formats.

Usage:
    python3 tools/trace_game.py TRACE.jsonl.gz SEAT [SEAT ...] [--seed N] [--steps N]

Each seat must already be joined (`tfm join ... --as NAME`) on a local server. Every seat follows the
agent loop from AGENT_INSTRUCTIONS.md: `tfm turn` at the start of each turn, then `tfm play` until it
prints "Your turn is done". Moves are random (as in random_bot.py).

The trace has one JSON object per line:
    {"kind": "turn", "seat", "view", "seen", "logs", "text"}   the inputs to and output of one `turn`
    {"kind": "play", "seat", "text"}                           the output of one `play`
so other renderers can be replayed over exactly the same game.
"""
import argparse
import contextlib
import copy
import gzip
import io
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tfm import cli, digest, options, seats  # noqa: E402
from tfm.client import Client  # noqa: E402
from random_bot import values_for, weight as random_weight  # noqa: E402


def weight(leaf):
    """Like random_bot's weights, but favouring card plays so tableaus grow as in real games."""
    w = random_weight(leaf)
    label = leaf.label.lower()
    if w and label.startswith("play project card"):
        return 80
    if w and (label.startswith("standard projects") or label.startswith("sell patents")):
        return 2
    return w


def run(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("trace")
    parser.add_argument("seats", nargs="+")
    parser.add_argument("--steps", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    random.seed(args.seed)

    captured = []
    orig_summarize = digest.summarize

    def recording_summarize(view, ctx, new_logs, award_history=None):
        captured.append({"view": copy.deepcopy(view), "seen": sorted(ctx.seen), "logs": list(new_logs)})
        return orig_summarize(view, ctx, new_logs, award_history)

    digest.summarize = recording_summarize

    def cli_out(argv):
        buf = io.StringIO()
        code = 0
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                cli.main(argv)
        except SystemExit as e:
            code = e.code or 0
        return code, buf.getvalue()

    need_turn = {name: True for name in args.seats}
    turns = plays = 0
    with gzip.open(args.trace, "wt") as out:
        def write(rec):
            out.write(json.dumps(rec) + "\n")

        for _step in range(args.steps):
            acted = False
            for name in args.seats:
                seat = seats.load(name)
                view = Client(seat["server"], seat["player_id"]).player()
                if view["game"]["phase"] == "end":
                    print(f"game over: generation {view['game']['generation']}, {turns} turns, {plays} plays")
                    return 0
                wf = view.get("waitingFor")
                if wf is None or wf.get("optional"):
                    continue
                if need_turn[name]:
                    captured.clear()
                    _code, text = cli_out(["--seat", name, "state"])
                    rec = captured[0] if captured else {"view": None, "seen": [], "logs": []}
                    write({"kind": "turn", "seat": name, **rec, "text": text})
                    turns += 1
                    need_turn[name] = False
                    view = Client(seat["server"], seat["player_id"]).player()
                    wf = view.get("waitingFor")
                ctx = options.Context(view, set(), False)
                leaves = options.leaves(wf, ctx)
                for _attempt in range(8):
                    pool = [lf for lf in leaves if weight(lf) > 0] or leaves
                    leaf = random.choices(pool, weights=[weight(lf) or 1 for lf in pool])[0]
                    code, text = cli_out(["--seat", name, "play", leaf.id, *values_for(leaf, ctx)])
                    if code == 0:
                        write({"kind": "play", "seat": name, "text": text})
                        plays += 1
                        acted = True
                        if "Your turn is done" in text or "GAME OVER" in text:
                            need_turn[name] = True
                        break
                    if code == 2:
                        break
            if not acted:
                print("nobody could act; stopping")
                return 1
    print("step limit reached")
    return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
