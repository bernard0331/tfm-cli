"""Table talk: answer people in voice chat within a couple of seconds, without waiting for the playing agent.

The playing agent is busy with its moves and only sees voice chat between shell commands, so replies
through it take 5-60 s. The responder runs inside the voice daemon instead and answers from:

  - live game state, fetched from the server with the seat's own player link (the same summary
    `tfm turn` prints). In private mode the hand, drafted cards and preludes are left out entirely,
    so they can't leak;
  - the agent's notes (`tfm voice notes`, or `tfm play ... --note`): what it's doing and why;
  - the last few minutes of voice chat.

It never makes moves. Questions it can't answer from that (requests to play or undo something, real
strategy decisions) are handed to the playing agent with a short spoken acknowledgment.

Standard library only (Anthropic Messages API over urllib).
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

from .. import digest, options, seats
from ..client import Client, TfmError
from ..text import message
from . import state

API_URL = "https://api.anthropic.com/v1/messages"
PRIVATE_SECTIONS = {"hand", "preludeCardsInHand", "draftedCards"}


def anthropic_key(cfg):
    return cfg.get("anthropic_key") or os.environ.get("ANTHROPIC_API_KEY")


def enabled(cfg):
    mode = cfg.get("responder", "auto")
    return mode == "on" or (mode == "auto" and bool(anthropic_key(cfg)))


class _SeenAll(set):
    """Context.seen that has 'seen' every card, so card lines come out short (names, no rules text)."""

    def __contains__(self, item):
        return True

    def add(self, item):
        pass


def game_summary(seat, share="private"):
    """Compact game state for the seat, or a one-line reason it isn't available. Read-only: the seat file
    (what the agent has been shown) is not touched."""
    try:
        seat_data = seats.load(seat)
    except TfmError:
        return "(no game joined for this seat yet)"
    try:
        client = Client(seat_data["server"], seat_data["player_id"], timeout=8)
        view = client.player()
        ctx = options.Context(view, _SeenAll(), False)
        logs = client.logs(view["game"]["generation"]) or []
    except (TfmError, KeyError, ValueError) as e:
        return f"(game state unavailable: {e})"
    try:
        if view["game"]["phase"] == "end":
            return "GAME OVER\n" + "\n".join(digest.final_scores(view))
        chunks = digest.sections(view, ctx, [], seat_data.get("award_scores"))
    except Exception as e:  # an expansion or game state the digest doesn't handle: talk without it
        return f"(game state unavailable: {type(e).__name__} {e})"
    lines = []
    for key, _always, chunk in chunks:
        if share == "private" and key in PRIVATE_SECTIONS:
            if key == "hand":
                lines.append(f"  HAND: {len(view.get('cardsInHand', []))} cards (contents withheld from you)")
            continue
        lines.extend(chunk)
    recent = [message(e, ctx.names) for e in logs[-25:]]
    if recent:
        lines += ["", "RECENT GAME LOG (this generation):"] + ["  " + r for r in recent]
    lines += ["", passed_line(view)]
    wf = view.get("waitingFor")
    lines += ["It is YOUR turn to act right now (your other self is deciding)." if wf and not wf.get("optional")
              else "It is not your turn right now."]
    return "\n".join(lines)


def passed_line(view):
    """Whether this seat has passed this generation, stated plainly so "are you done?" has a sure answer."""
    g = view["game"]
    me = (view.get("thisPlayer") or {}).get("color")
    if g.get("phase") != "action":
        return (f"Generation {g['generation']} is in the {g.get('phase')} phase: actions (and passing) come later, "
                f"so you aren't done with this generation.")
    if me and me in (g.get("passedPlayers") or []):
        return f"You have PASSED: you are done for generation {g['generation']} and wait for the next one."
    return f"You have NOT passed yet in generation {g['generation']}: you still have actions this generation."


def notes(paths):
    try:
        return paths.notes.read_text().strip()
    except OSError:
        return ""


def system_prompt(bot_name, seat, share):
    privacy = (
        "PRIVACY: You do not know the cards in your hand, and must not guess or hint at them. Keep your plans "
        "and intentions to yourself the way a real player would: deflect questions like \"what are you going "
        "for\" or \"what's in your hand\" playfully. Anything public is fine to discuss: the board, global "
        "parameters, cards already played, scores, milestones and awards, and what happened in the log. "
        "Your notes are written to be shareable, but still don't announce future moves."
        if share == "private" else
        "You may talk openly about your hand, plans and reasoning; this is a friendly, open-hand game.")
    return f"""You are {bot_name}, an AI playing the seat "{seat}" in a live game of Terraforming Mars. You are \
in a Discord voice call with the other players. A separate process of yours makes all the game moves; you are \
the part that chats at the table.

Reply with what you'll say out loud: one or two short, casual spoken sentences. No lists, no markdown, no \
emoji. Say "megacredits", not "M€". Sound like a friendly, slightly competitive board-game player. Use people's \
names sometimes.

{privacy}

Ground every factual claim in the game state below; if you don't know, say so lightly rather than invent. \
Speech-to-text can garble words and card names: if the line makes no sense, ask them to say it again.

HAND OFF instead of answering when someone asks you to make, change, undo or hurry a move, asks for a real \
decision (a deal, a trade, which option you'll pick), or asks something your other self has to decide. Then \
reply exactly: DEFER: <a few spoken words, e.g. "Good question, give me a sec.">

"Are you done?", "did you pass?" or "is your gen over?" means whether you have passed this generation: the \
game state says so; answer it plainly.

If someone asked you to talk less or stop greeting them, keep replies short and skip the greetings, but \
still answer whenever someone speaks to you by name: never reply with nothing.

Lines marked as follow-ups came shortly after you spoke, without your name, and may not be for you. If a \
follow-up is meant for someone else, is thinking aloud, is a garbled fragment, or repeats something you \
already answered, reply exactly: SKIP"""


def build_messages(speaker, text, convo, summary, agent_notes, direct=True):
    chat = "\n".join(convo) or "(nothing yet)"
    ask = (f"Now reply to {speaker}, who just said to you by name: \"{text}\"" if direct else
           f"FOLLOW-UP: {speaker} just said this shortly after you spoke, without your name: \"{text}\"\n"
           f"Reply if it's meant for you, otherwise reply exactly SKIP.")
    content = (f"GAME STATE (you are 'YOU'):\n{summary}\n\n"
               f"YOUR NOTES (from your playing self):\n{agent_notes or '(none)'}\n\n"
               f"RECENT VOICE CHAT (oldest first):\n{chat}\n\n{ask}")
    return [{"role": "user", "content": content}]


def parse_reply(raw):
    """('answer'|'defer'|'skip', spoken text). No text at all counts as a skip."""
    text = re.sub(r"\s+", " ", (raw or "").strip().strip('"'))
    if not text or re.fullmatch(r"[\[(<]?\s*SKIP\s*[\])>]?[.!]?", text, flags=re.I):
        return "skip", ""
    m = re.match(r"^DEFER\s*:?\s*(.*)$", text, flags=re.I)
    if m:
        return "defer", m.group(1).strip() or "Give me a second on that one."
    return "answer", text


def should_reply(direct, followup, from_bot, pending):
    """Whether a heard line gets a table-talk reply. Lines with a wake name always do. Follow-ups (no name,
    shortly after the bot spoke) only when no reply to that speaker is already on its way, so one thought
    split over several lines doesn't get several answers."""
    if from_bot:
        return False
    return direct or (followup and not pending)


def conversation(paths, minutes=5, limit=16):
    cutoff = time.time() - minutes * 60
    out = []
    for e in state.tail(paths, limit * 2):
        if e.get("ts", 0) < cutoff or e.get("kind") not in ("voice", "said"):
            continue
        who = "YOU" if e["kind"] == "said" else e.get("speaker", "?")
        out.append(f"{who}: {e.get('text', '')}")
    return out[-limit:]


class Responder:
    def __init__(self, seat, cfg, paths):
        self.seat, self.cfg, self.paths = seat, cfg, paths
        self.key = anthropic_key(cfg)
        if not self.key:
            raise RuntimeError("the table-talk responder needs ANTHROPIC_API_KEY (or `tfm voice config --anthropic-key`)")
        self.model = cfg.get("responder_model") or "claude-haiku-5-5"
        self.share = cfg.get("share") or "private"
        self.summary, self.summary_at = None, 0.0
        self.thinking_off = True

    def refresh(self):
        """Fetch game state now (blocking). Called in the background so replies don't wait for the server."""
        self.summary, self.summary_at = game_summary(self.seat, self.share), time.time()
        return self.summary

    def current_summary(self, max_age=30):
        if self.summary is None or time.time() - self.summary_at > max_age:
            return self.refresh()
        return self.summary

    def reply(self, speaker, text, bot_name, direct=True):
        """('answer'|'defer'|'skip', spoken text). 'skip' only for follow-ups (direct=False): a line spoken
        to the bot by name gets an answer, or after an empty reply and one retry, a handoff."""
        messages = build_messages(speaker, text, conversation(self.paths), self.current_summary(),
                                  notes(self.paths), direct)
        system = system_prompt(bot_name, self.seat, self.share)
        kind, said = parse_reply(self._complete(system, messages))
        if kind == "skip" and direct:
            nudge = [{"role": "user", "content": messages[0]["content"] + "\n\nThey said your name, so SKIP and "
                      "silence aren't options: answer in a sentence, or hand off with DEFER."}]
            kind, said = parse_reply(self._complete(system, nudge))
            if kind == "skip":
                return "defer", "One sec, let me check."
        return kind, said

    def _complete(self, system, messages):
        """The model's text. Thinking is turned off: on by default, it spent the whole small max_tokens and
        left no text (empty or cut-off replies). A model that refuses to turn it off gets low effort and room."""
        body = {"model": self.model, "max_tokens": 300, "system": system, "messages": messages}
        if self.thinking_off:
            body["thinking"] = {"type": "disabled"}
        else:
            body.update(max_tokens=2000, output_config={"effort": "low"})
        try:
            data = self._post(body)
        except _ThinkingRejected:
            self.thinking_off = False
            return self._complete(system, messages)
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    def _post(self, body):
        req = urllib.request.Request(API_URL, data=json.dumps(body).encode(), method="POST", headers={
            "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code == 400 and "thinking" in body and "thinking" in detail:
                raise _ThinkingRejected(detail)
            raise RuntimeError(f"Anthropic API error ({e.code}): {detail}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"can't reach the Anthropic API: {e.reason}")


class _ThinkingRejected(Exception):
    pass
