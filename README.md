# tfm: Terraforming Mars from the terminal, for AI agents

`tfm` lets any agent that can run shell commands (Claude Code, Codex, and others) play a seat in a
game on [terraforming-mars.herokuapp.com](https://terraforming-mars.herokuapp.com) or a local
server. Each decision costs one short text read (about 1k tokens) and one command, instead of page
reloads and screenshots. Agents can only choose from the moves the app itself offers, so they can't
make illegal moves.

No dependencies: Python 3.9+ standard library only.

## Install

```bash
pip install -e .
```

`tfm` must be on the PATH of every app that will play: the Claude app's Code tab and Codex. If
`pip` installs it somewhere else, use `pipx install -e .`, or run it as `python3 -m tfm` from this
folder.

## Play a game against agents

1. Create the game in the web app as usual, with a seat for each agent (e.g. `claude`, `gpt`).
2. In each agent's chat, say:

   > Read `<path>/tfm-cli/AGENT_INSTRUCTIONS.md` and `<path>/tfm-cli/docs/STRATEGY.md`. You are seat
   > `claude`. Your player link is `https://terraforming-mars.herokuapp.com/player?id=p…`. Play the
   > game to the end and try to win.

   [`docs/STRATEGY.md`](docs/STRATEGY.md) is the strategy and rules context agents play from. Improve it
   as you learn from games.

3. You and your friends play in the browser as normal.

### Auto or confirm

- **Auto** (default): the agent submits its own moves. To stop the Claude app asking permission
  before each command, allow `tfm` commands in its permission settings.
- **Confirm**: tell the agent to join with `--confirm`. Every `tfm play` then only proposes the move,
  and the agent reruns it with `--yes` after you agree. That relies on the agent following the
  instructions. For a hard guarantee, leave `tfm play` un-approved in the app's permission settings,
  so the app itself asks you before each move is sent.

## Agent-only or test games on a local server

```bash
git clone https://github.com/terraforming-mars/terraforming-mars
cd terraforming-mars && npm ci && npm run build && PORT=8765 npm start   # needs Node 22
tfm new-game my_settings.json --server http://localhost:8765 --players claude,gpt,me
```

`new-game` takes the same JSON the web app's settings export produces, and prints one player link per
seat. [`examples/settings.json`](examples/settings.json) is a full example (most expansions on, draft,
preludes, fan milestones and awards, clock penalty); `--players` replaces its player list. On a local server nobody else is affected, and you can run the random-move stress test:

```bash
python3 tools/random_bot.py seat1 seat2 seat3
```

## Commands

| Command | What it does |
|---|---|
| `tfm join LINK [--as NAME] [--confirm]` | Save a seat (stored in `~/.tfm/seats`; override with `TFM_HOME`) |
| `tfm -s NAME turn [--wait S] [--full]` | Wait for your turn, then print the state and numbered choices |
| `tfm -s NAME play ID [VALUE ...]` | Submit a choice |
| `tfm -s NAME state` / `options` | Print state and choices / choices only, without waiting |
| `tfm -s NAME board` / `log` | List tiles / this generation's log |
| `tfm card NAME ...` | Card text from the bundled card data |
| `tfm -s NAME value [CARD ...] [--gens N]` | Estimate what cards are worth in M€ now (default: the cards in your pending decision and hand), with context checks. `turn --value` / `state --value` append the same report |
| `tfm seats` / `tfm leave NAME` | List / remove saved seats |
| `tfm new-game SETTINGS.json --server URL [--players a,b]` | Create a game and print player links |

### Safety checks

- `play` refuses to submit if your choices changed since you last listed them (a stale id could
  mean a different move), and reprints the current ones instead.
- Payments are checked against your resources and the card's payment rules before they're sent.
- On a server rejection, the reason and the current choices are printed.

### `tfm value`

`tfm value` prices each card's declared effects at fixed rates (1 VP = 5 M€, 1 TR = 8.5 M€, plus
derived rates for heat, plants, metals and cards in [`docs/STRATEGY.md`](docs/STRATEGY.md) §6), with
production counted only for the production phases the game is likely to have left. It prints the
price (play cost, plus 3 M€ when you'd be buying the card), the estimated value, the net and the
ratio, then context checks on the live game:

- global-parameter bonus thresholds the card crosses (−24/−20°C heat production, 0°C ocean, 8% oxygen
  temperature step, Venus 8% card and 16% TR, alternative Venus board rewards) and when it takes the
  last step of a parameter or completes terraforming;
- Pathfinders planetary-track rewards its tags trigger, for you and for every player;
- milestones it would let you claim, and award placings it changes for you and each rival;
- requirements it meets for cards in your hand, or requirements it doesn't meet yet;
- rivals' cards that pay out when you do this, and who can block an attack;
- Underworld digs: excavation is priced from the tokens still in the bag (or the best identified
  token you can reach), identify-and-claim as the best of the identified tokens, and corruption by
  whether it cancels your negative VP;
- effects the numbers can't cover (custom card code, ongoing effects), marked `?` to read yourself.

Standard projects and conversions (`tfm value Asteroid:SP Excavate:SP "Convert Heat"`) are priced the
same way, so you can compare a card with the standard project it would replace.

Generations left come from the table's recent terraforming pace, capped at a typical game length
for the player count; override with `--gens`. The numbers are estimates for comparing options.

## Updating card data

`tfm/data/` holds card text and effects, milestone and award descriptions, colonies and board adjacency, exported
from the app's source code. After a big app update, rebuild the data from a built checkout of the app:

```bash
cp tools/tfm_cli_export.ts tools/tfm_cli_cards_export.ts <app>/src/tools/
(cd <app> && npx tsx src/tools/tfm_cli_export.ts /tmp/tfm_export.json)
(cd <app> && npx tsx src/tools/tfm_cli_cards_export.ts /tmp/tfm_cards_export.json)
python3 tools/build_data.py <app> /tmp/tfm_export.json /tmp/tfm_cards_export.json
```

`behaviors.json` (each card's declared effects and the planetary tracks, used by `tfm value`) comes
from the second export.

## Limits

- Card text for a few cards is rebuilt from their icons and reads roughly. Use `tfm card` or the
  [card list](https://terraforming-mars.herokuapp.com/cards) when one is unclear.
- Turmoil, Moon and other expansions turned off in your usual settings haven't been tested. Their
  input types are handled generically, but if a step says "unsupported", make that move in the web UI.
- Opponents' VP are hidden whenever the game hides them (`showOtherPlayersVP: false`).
