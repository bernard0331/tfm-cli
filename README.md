# tfm: Terraforming Mars from the terminal, for AI agents

`tfm` lets any agent that can run shell commands (Claude Code, Codex, and others) play a seat in a
game on [terraforming-mars.herokuapp.com](https://terraforming-mars.herokuapp.com) or a local
server. Each decision costs one short text read (about 1k tokens) and one command, instead of page
reloads and screenshots. Agents can only choose from the moves the app itself offers, so they can't
make illegal moves.

No dependencies: Python 3.9+ standard library only. (Optional [Discord voice chat](#voice-chat-on-discord) adds a few.)

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

## Voice chat on Discord

An agent can sit in your Discord voice channel while it plays: it hears what the table says (speech to
text) and talks back (text to speech). A small background daemon (a Discord bot) does the audio;
the agent only runs `tfm` commands. `tfm turn` shows what was said since the agent last looked, and
returns early when someone says the seat's name, so the agent can answer even when it isn't its turn.

### One-time setup

1. **Create the bot.** In the [Discord Developer Portal](https://discord.com/developers/applications):
   New Application → **Bot** → *Reset Token* and copy it. No privileged intents are needed.
   Then **OAuth2 → URL Generator**: scope `bot`, permissions *View Channels*, *Connect*, *Speak*
   (and *Send Messages* if you want `--text-chat`). Open the generated URL to add the bot to your server.
   Use one bot (one token) per agent seat.
2. **Install** (macOS, in the same venv as `tfm`):
   ```bash
   brew install opus
   pip install -e ".[voice]"            # discord.py 2.7+ (with DAVE encryption) and voice receive
   ```
3. **Pick speech engines.** Speech to text: the OpenAI API (fast, accurate, a fraction of a cent per
   line; set `OPENAI_API_KEY` or `--openai-key`) or offline with `pip install -e ".[voice-local]"`
   (faster-whisper; slower on CPU, and may not have wheels for the newest Python yet). Text to speech: macOS `say` by
   default (free; nicer voices under System Settings → Accessibility → Spoken Content → Manage Voices),
   or `--tts openai`.
4. **Configure the seat** (right-click the voice channel → *Copy Link*; you're prompted for the token):
   ```bash
   tfm -s claude voice config --channel https://discord.com/channels/<server>/<channel> --voice Zoe
   tfm -s claude voice test --play      # speaks a line on your speakers, then transcribes it back
   ```
   The config is saved in `~/.tfm/voice/claude/` (token file is private to your user), so this is once
   per seat, not per game.

### Fast table talk (recommended)

Answers through the playing agent take 5–60 s, since it only checks voice chat between its own game
commands. With an Anthropic API key, the daemon answers by itself in about 2 s using a small fast model
(`claude-haiku-5-5`; pay-as-you-go, a fraction of a cent per reply):

```bash
tfm -s claude voice config --anthropic-key sk-ant-...     # or set ANTHROPIC_API_KEY
tfm -s claude voice ask "claude, who's winning?"         # try a reply here, without Discord
```

Each reply sees live game state, fetched from the server with the seat's link (the same summary as
`tfm turn`), the agent's notes (`voice notes`, or `tfm play ... --note "..."`), and the last few minutes
of chat, including whether the seat has passed this generation (so "are you done?" gets a straight
answer). Thinking is turned off for these replies: it's what keeps them at about a second. It only talks: requests to make or undo a move, deals and real decisions are handed to the
playing agent, which `tfm turn` wakes up for, after a short spoken "give me a sec".

`--share private` (the default) keeps the hand and plans hidden: the hand, drafted cards and preludes are
never sent to the model, so they can't slip out, and it deflects questions about plans. `--share open`
sends everything, for open-hand or coaching games. `--responder off` turns auto-replies off.

### Playing with voice

Start voice before the game (or let the agent do it), and add a line to the agent's prompt:

```bash
tfm -s claude voice start
```

> Voice chat is on: read the "Voice chat" section of AGENT_INSTRUCTIONS.md.

| Command | What it does |
|---|---|
| `tfm -s NAME voice start` / `stop` / `status` | Start the daemon and join the channel / leave / who's there, errors |
| `tfm -s NAME voice say TEXT [--interrupt] [--text-chat] [--wait]` | Speak (queued; returns at once unless `--wait`) |
| `tfm -s NAME voice listen [--wait S] [--last N]` | What people said since the last look (`turn`, `state` and `play` show it too) |
| `tfm -s NAME voice notes [TEXT] [--append]` | Notes table talk answers from (`tfm play ... --note TEXT` sets them too) |
| `tfm -s NAME voice ask TEXT [--show-context]` | Try a table-talk reply without Discord |
| `tfm -s NAME voice config ...` | Token, channel, `--stt`/`--tts` engines, `--voice`, `--rate`, `--volume`, extra wake `--name`s, `--silence-ms`, `--responder`, `--share`, `--anthropic-key` |
| `tfm -s NAME voice test [TEXT] [--play]` | Try the speech engines without Discord |

Notes:

- **Wake names**: the seat name plus common mishearings (for `claude`: cloud, clod, …), the bot's
  display name, and any `--name` you add. For 20 seconds after the bot speaks, lines without the name
  count as follow-ups, so a conversation doesn't need the name in every line (`followup_s` in the
  seat's `config.json`). Table talk may stay quiet on a follow-up that isn't for it (talk to someone
  else, a garbled fragment, a repeat), and while a reply to someone is still being written or waiting
  to be spoken, their further follow-ups are only context, so one thought gets one answer. A line with
  the name always gets an answer: if the model comes back empty it retries once, then hands the line
  to the playing agent with a spoken "one sec". Bots saying the name don't wake the agent, so two agent
  seats can't talk each other into a loop.
- **Latency**: with table talk on, about 2 s after you stop talking (0.55 s pause detection,
  transcription, the reply, then speech, which starts on the first sentence). Questions handed to the
  playing agent take as long as it does: fastest while it waits in `tfm turn`.
- **Encryption**: Discord requires end-to-end encrypted voice (DAVE) since March 2026. discord.py 2.7
  handles it for speaking; for listening, `tfm` patches discord-ext-voice-recv with the decryption step
  proposed upstream ([PR #58](https://github.com/imayhaveborkedit/discord-ext-voice-recv/pull/58)) until
  the extension ships its own. If the bot speaks but never hears anyone, check `~/.tfm/voice/<seat>/bot.log`
  and run `voice start --debug`.
- The daemon runs on until `voice stop` (or the computer sleeps). Its log is `~/.tfm/voice/<seat>/bot.log`.

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
| `tfm -s NAME play ID [VALUE ...] [--expect TEXT]` | Submit a choice; `--expect` refuses if the option no longer contains TEXT |
| `tfm -s NAME state` / `options` | Print state and choices / choices only, without waiting |
| `tfm -s NAME board` / `log` | List tiles / this generation's log |
| `tfm -s NAME vp` | Every player's VP if the game ended now: yours from the app, rivals' recomputed from public info (TR, milestones, award standings, tiles, played cards) |
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

`tfm value` prices each card's declared effects at baseline rates (1 VP = 5 M€; 1 TR = 5 M€ + 1 M€ per
remaining spendable production phase; heat and plants derived from TR; metals and cards in [`docs/STRATEGY.md`](docs/STRATEGY.md) §6), with
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
