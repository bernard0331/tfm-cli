# Plan: long-term planning and combo recognition in `tfm value`

`tfm/value.py` prices one card at a time against the player's current tableau. Anything that depends on
future plays is either a fixed guess or priced at 0, which is where agents miss combos and long-term plans.
This plan splits the fix into three pieces that can be built on separate branches and merged in order
1 → 2 → 3.

## Gaps in the current model

- **Effect cards score 0 for their effect when you consider buying them.** `OWN_TRIGGERS` only pays out
  for owners already on the tableau (`_own_triggers`). The card being valued gets a `?` note
  ("ongoing effect ... value depends on future plays") from `value_card`, so Arklight, Decomposers,
  Media Group, Point Luna, etc. look worse than they are.
- **Discounts are a flat guess.** `cardDiscount` assumes ~1 matching play per generation for a tag
  discount (2.5 for a general discount), whatever the hand holds.
- **VP per tag counts current tags only** (`vp: {"tag": ...}` in `value_card`).
- **Requirement unlocks are a flag, not M€** (`_unlocks`); a not-yet-playable card has no estimate of
  when it becomes playable.
- **No timing.** 1 M€ is worth the same every generation; production is rate × remaining phases. There is
  no "play now vs later" or "save for the big card" reasoning.
- **Steel/titanium value raises** are left as manual notes.

## Shared rules for all three pieces

- **Keep agent output short.** Agents pay for every line `tfm value` prints, every turn. New output is
  at most one short line per card (e.g. `combo: +6.0 (Arklight ×3 plant cards in hand)`); detail goes
  behind a flag.
- **No tuning to our own games.** We have 3 finished real games — far too few to fit constants. Derive
  numbers from the rules and the card data (`tfm/data/cards.json`, `behaviors.json`), and state every
  assumption as a named constant with a comment.
- **Tests use hand-built views**, in the style of `tests/test_value.py` (`view(...)` helper). Run with
  `python3 -m unittest discover tests`. All existing tests must keep passing.
- **Standard library only**, Python 3.9+.

## Approach 1 — the hand counts as future plays (combo recognition)

Files: `tfm/value.py`, `tests/test_value.py`.

Treat the tableau plus the hand cards you are likely to play as a **planned tableau**:

- **Play probability per hand card**: can it be afforded within the remaining generations, and will its
  requirement be met before the game ends at the current terraforming pace? (0–1; simple and explained.)
- **Effect cards in hand or being valued**: price `OWN_TRIGGERS` / discount / VP-per-tag effects from
  expected future matches = Σ matching planned cards × their play probability + `future_matches(ctx, event)`
  (a hook; return 0 here — Approach 2 fills it in).
- **The reverse direction**: a card that fires an effect card in hand that you will likely play gets
  partial credit.
- **Requirement unlocks** are priced as how much earlier the locked card can be played, instead of a
  flag only.
- **No double counting**: price combos as the marginal value of the card to the planned set (set with it
  minus without it).

Done when Arklight + 3 plant cards, Point Luna + Earth cards, Ecological Zone + animals/plants, and a
discount card + matching hand each score clearly above the same cards with an unrelated hand, and the
existing tests still pass.

## Approach 2 — expected future draws

Files: new `tfm/deck.py`, `tests/test_deck.py`; in `value.py` only the body of the `future_matches` hook.

- From the card data, compute the share of project cards in the deck with each tag / type / trait that
  `OWN_TRIGGERS` and discounts react to (`tag:<t>`, `card:<t>`, `event`, `space_event`, `cost20`,
  `notags`, `onetag`, `tag:bio`), filtered to the game's enabled expansions (`gameOptions`).
- `future_matches(ctx, event) -> float` = share × cards seen per generation × share of seen cards that
  get played × `ctx.gens_left`. Cards seen and played per generation are named constants derived from the
  rules (draft of 4, buying behaviour), documented, not fitted.
- Optionally expose the same rates for milestone/award projections, but don't change those yet.

Done when Point Luna in generation 1 with no Earth cards gets positive value that shrinks as
`gens_left` falls, and shares are computed from the data rather than hard-coded.

## Approach 3 — simulate the rest of the game (long-term planning)

Files: new `tfm/plan.py`, `tests/test_plan.py`, a new `tfm plan` command in `tfm/cli.py`.

A simplified simulation of the player's own economy over the remaining generations:

- State: M€, production, steel/titanium (with their values), plants, heat, tags, tableau, and global
  parameters advancing at the table's pace (`Outlook.pace`).
- Each simulated generation: income; play affordable hand cards greedily by value per cost at that point
  in the game (using `value.value_card` with a context for that generation); convert plants/heat; spend
  leftovers on standard projects; draw "average cards" (use `future_matches` / a flat card value until
  Approach 2 lands).
- Output: projected final VP. A decision's value = projected VP with it minus without it.
- `tfm plan` prints the projected score and the planned play order, and with `--opening` scores a
  corporation + preludes + kept hand as one bundle. **Do not add its output to `turn` / `state` by
  default.**
- Known limits to document: rivals mostly ignored, no board placement, greedy play order.

Done when tests show production cards played before VP cards early, a card with a requirement played
once the requirement would be met, and saving for an expensive high-value card beating two weak buys;
and `tfm plan --opening` ranks a strong synthetic opening above a weak one.

## Status

All three are implemented and merged (1 → 2 → 3). `value.future_matches` delegates to `tfm/deck.py`;
Approach 2's interim pricing was dropped in favour of Approach 1's planned-tableau pricing, and `tfm plan`
uses the deck rates for its future-card stream. Not yet tried in a live game.
