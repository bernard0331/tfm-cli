"""Replay a trace from trace_game.py through output formats and compare their size.

Usage:
    python3 tools/compare_output.py TRACE.jsonl.gz [...]

For every recorded `turn` it renders:
    full       the current output (checked byte-for-byte against the recorded text)
    gen        only changed sections, with a full snapshot on the first turn of each generation
    never      only changed sections, never a full snapshot after the first turn
    gen-lines / never-lines   the same, comparing milestones, awards and colonies line by line
and, for gen and never, rebuilds the full text from the previous rebuild plus the new output, reading
only the printed text (as an agent would), and checks it equals the full output.
"""
import contextlib
import gzip
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tfm import cli, digest, options  # noqa: E402


MODES = ("gen", "never", "gen-lines", "never-lines")


def strip_clock(text):
    return "\n".join(ln for ln in text.split("\n") if not ln.startswith("  clock "))


def tokens(text):
    return len(text) / 4  # rough: ~4 characters per token


def options_text(view, ctx):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli._print_options(view, ctx, {})
    return buf.getvalue()


# ------------------------------------------------------------ reading the printed text back

OPP_HEAD = re.compile(r"^  (\S.*?) \((\w+)\) · ")


def parse(text):
    """Split a printed summary into section key -> lines, using only what is printed."""
    out = defaultdict(list)
    key = "game"
    opp = None
    in_opps = False
    for line in text.split("\n"):
        if line.startswith("UNCHANGED since your last turn"):
            key = "note"
        elif line.startswith("YOU: "):
            key, in_opps = "you", False
        elif line == "OPPONENTS:":
            key, in_opps = "opps", True
        elif line.startswith(("MILESTONES", "AWARDS", "COLONIES")):
            key, in_opps = line.split()[0].lower(), False
        elif line == "SINCE YOUR LAST LOOK:":
            key, in_opps = "log", False
        elif line.startswith("YOUR DECISION") or line.startswith("No decision pending"):
            key, in_opps = "decision", False
        elif line == "":
            key = key if key in ("log", "decision") else ""
        elif in_opps and OPP_HEAD.match(line):
            opp = OPP_HEAD.match(line).group(1)
            key = f"opp.{opp}"
        elif in_opps and line.startswith("    tags: "):
            key = f"opp.{opp}.tags"
        elif in_opps and line.startswith("    played: "):
            key = f"opp.{opp}.played"
        elif key.startswith("you") or key in ("hand", "preludeCardsInHand", "draftedCards"):
            for prefix, k in (("  tags: ", "you.tags"), ("  tiles: ", "you.tiles"), ("  played: ", "you.played"),
                              ("  card actions used", "you.actions"), ("  clock ", "you.clock"), ("  HAND (", "hand"),
                              ("  PRELUDES IN HAND", "preludeCardsInHand"), ("  DRAFTED", "draftedCards")):
                if line.startswith(prefix):
                    key = k
                    break
        out[key].append(line)
    return out


def merge_lines(old, new):
    """A line-level section: header from the new output, each named line from new if printed, else old."""
    header = new[0].split(" (only changed lines;")[0]
    printed = {digest._line_key(ln): ln for ln in new[1:]}
    rows = [printed.pop(digest._line_key(ln), ln) for ln in old[1:]]
    return [header] + rows + list(printed.values())


def rebuild(prev, printed, order, by_line=False):
    """Full text from the previous rebuild plus the latest output, as a reader would combine them."""
    new = parse(printed)
    old = parse(prev) if prev else {}
    if by_line:
        for key in digest.LINE_LEVEL:
            if key in new and "(only changed lines;" in new[key][0] and key in old:
                new[key] = merge_lines(old[key], new[key])
    skipped = set()
    for line in new.get("note", []):
        skipped |= {s.strip() for s in line.split(": ", 1)[1].split(", ")}
    merged = []
    for key in order:
        if key in new:
            merged.append((key, new[key]))
        elif digest.section_name(key) in skipped and key in old:
            merged.append((key, old[key]))
    return merged


def flatten_by_order(chunks, by_key):
    """Lay out sections in the full output's order."""
    lines, done = [], set()
    for key, _always, _lines in chunks:
        if key in done:
            continue
        done.add(key)
        lines.extend(by_key.get(key, []))
    return lines


# ------------------------------------------------------------ main

def run(paths):
    totals = defaultdict(float)
    sizes = defaultdict(float)
    mismatches = defaultdict(int)
    turns = plays = 0
    for path in paths:
        memory = {mode: {} for mode in MODES}
        last_text = {mode: {} for mode in MODES}
        last_gen = {}
        extra_seen = defaultdict(set)  # "seen" markers the recorded game did not have (colony text)
        with gzip.open(path, "rt") as f:
            for raw in f:
                rec = json.loads(raw)
                seat = rec["seat"]
                if rec["kind"] == "play":
                    plays += 1
                    totals["play"] += tokens(rec["text"])
                    continue
                if rec["view"] is None:
                    continue
                turns += 1
                view, logs = rec["view"], rec["logs"]
                ctx = options.Context(view, set(rec["seen"]) | extra_seen[seat], False)
                chunks = digest.sections(view, ctx, logs)
                extra_seen[seat] |= {k for k in ctx.seen if k.startswith("col:")}
                opt = options_text(view, ctx)
                full = "\n".join(line for _k, _a, ls in chunks for line in ls) + "\n\n" + opt
                if strip_clock(full) != strip_clock(rec["text"]):
                    mismatches["full vs recorded"] += 1
                totals["full"] += tokens(full)
                for key, _always, lines in chunks:
                    sizes[key.split(".")[0] + (".played" if key.endswith(".played") else ".tags" if key.endswith(".tags") else "")] += tokens("\n".join(lines))
                sizes["decision"] += tokens(opt)

                gen = view["game"]["generation"]
                order = [k for k, _a, _l in chunks]
                for mode in MODES:
                    shown = memory[mode].get(seat, {})
                    if mode.startswith("gen") and last_gen.get(seat) != gen:
                        shown = {}
                    lines, now = digest.changes_only(chunks, shown, by_line=mode.endswith("lines"))
                    memory[mode][seat] = now
                    text = "\n".join(lines) + "\n\n" + opt
                    totals[mode] += tokens(text)
                    merged = rebuild(last_text[mode].get(seat), text, order, by_line=mode.endswith("lines"))
                    rebuilt = "\n".join(flatten_by_order(chunks, dict(merged)))
                    expect = "\n".join(line for _k, _a, ls in chunks for line in ls)
                    if [ln for ln in rebuilt.split("\n") if ln] != [ln for ln in expect.split("\n") if ln]:
                        mismatches[f"rebuild {mode}"] += 1
                        if mismatches[f"rebuild {mode}"] == 1:
                            Path("/tmp/claude-0/-home-user/7f411039-cdb8-553e-b759-70b760f63141/scratchpad/mismatch.txt").write_text(rebuilt + "\n=====\n" + expect)
                    last_text[mode][seat] = rebuilt + "\n"
                last_gen[seat] = gen

    print(f"{turns} turns, {plays} plays (tokens ≈ characters / 4)")
    print(f"  play outputs (same in every format): {totals['play']:,.0f} tokens total, {totals['play'] / plays:,.0f} per play")
    for mode, label in (("full", "full every turn"), ("gen", "changed sections, snapshot each generation"),
                        ("never", "changed sections, no snapshots"),
                        ("gen-lines", "changed lines, snapshot each generation"),
                        ("never-lines", "changed lines, no snapshots")):
        t = totals[mode]
        print(f"  {label:42s} {t:9,.0f} tokens · {t / turns:5,.0f} per turn · "
              f"{100 * (1 - t / totals['full']):4.1f}% less than full · "
              f"turn+play total {100 * (1 - (t + totals['play']) / (totals['full'] + totals['play'])):4.1f}% less")
    print("  full-output tokens by section, per turn:")
    for key, v in sorted(sizes.items(), key=lambda kv: -kv[1]):
        if v / turns >= 5:
            print(f"    {key or '(blank/headers)':20s} {v / turns:6,.0f}")
    print("  mismatches:", dict(mismatches) or "none")


if __name__ == "__main__":
    if "--once-colony-text" in sys.argv:
        sys.argv.remove("--once-colony-text")
        digest.ONCE_COLONY_TEXT = True
        print("(colony trade text printed once per seat)")
    run(sys.argv[1:])
