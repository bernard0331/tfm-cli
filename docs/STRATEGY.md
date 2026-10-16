# Terraforming Mars: strategy and rules context for agents

Context for an AI agent playing a seat with `tfm` (see [AGENT_INSTRUCTIONS.md](../AGENT_INSTRUCTIONS.md)):
a strategic framework, rules that commonly trip players up, expansion notes, and lessons from past
games. Read it once at the start of a game, not every turn.

It is **not** a card database or proof of optimal play. When a card interaction is unusual, the exact
card text (`tfm card "<name>"`), the live game settings and the choices `tfm` offers decide. Never carry
resources, coordinates or plans over from a previous game.

---

## Ten priorities

1. Read the actual setup from your first `tfm turn`: player count, map, expansions, milestones,
   awards, colonies, and whether the clock penalty is on.
2. Track stock and production separately. Note which card actions you've used and which fleets are free.
3. Estimate how many generations are left from **every** player's ability to finish the global
   parameters, and switch from buying production to buying points about two generations before the end.
4. After every card or tile, recheck **all** unclaimed milestones, not just the ones you were aiming for.
5. Keep cash in reserve for a milestone claim, an award fee or a contested opportunity before spending
   on optional development.
6. Drafting, buying and playing are three separate decisions. A good draft pick doesn't have to be worth buying.
7. Only place tiles on the spaces `tfm` lists, and read each space's bonus, costs and neighbours first.
8. Value a resource by its remaining uses. Heat after temperature is maxed is not automatic TR.
9. Before passing, look for unused scoring actions, trades, plant thresholds, milestones, awards and hand sales.
10. Keep routine turns fast. Save long thinking for the opening, award funding and the endgame.

---

## 1. Strategic model

Terraforming Mars is a competition over **time, capital, scoring opportunities and access**. Your
opponents help decide when your investments stop paying: an engine that needs three more generations
is weak if the table can end the game this generation.

Keep two projections:

- **Economic:** what can I afford and activate before the next production phase?
- **Scoring:** where will my final points come from if the game ends this generation, the next, or the
  one after? Break it into TR, milestones, awards, greeneries, cities, card and resource points,
  expansion points and penalties. `tfm` prints your VP breakdown every turn.

A weak category is fine if another route makes up for it. In recorded games the highest TR at the table
finished last, and the lowest TR finished second twice. For any candidate action, ask:

> What does this add to my likely final score, what does it enable, what does it give or deny the
> strongest rival, and what better action does its cost rule out?

Hidden hands, unknown draws and uncertain game length call for ranges and judgement, not fake precision.

### Main strategic directions

| Direction | When it is attractive | Main failure mode |
|---|---|---|
| Fast terraforming | Efficient heat, plants and events, and a lead that benefits from an early finish | Helping close the game while a rival scores more efficiently elsewhere |
| Economy and card engine | Early discounts or card draw, reliable things to spend on, enough generations left | Investing after the payback window has closed |
| Ground game | Plant supply, good placements, viable city sites, map-related scoring | Expensive empty cities, or greeneries that feed opponents' cities |
| Space/Jovian | Titanium supply, strong space cards, multipliers you can support | Collecting tags or metal with no affordable way to score them |
| Resources on cards | Repeatable animals, floaters, microbes or data with a good conversion | Buying a slow action too late, or resources stolen before they score |
| Colonies and trade | Profitable reachable colonies, a cheap way to pay for trades, useful owner bonuses | Assuming an attractive trade will still be there on your turn |

Most winning positions mix directions. Pick an initial emphasis, then adapt to the cards and opponents
you actually face.

---

## 2. Rules baseline

Normal multiplayer defaults; cards, maps and variants can override them.

- Each turn you take one or two actions; passing ends your participation for the generation.
- Research cards cost 3 M€ each to keep, separately from their play cost.
- Each blue-card action can normally be used once per generation.
- M€ income includes your TR. Leftover energy becomes heat before new energy is produced.
- 8 plants → a greenery; 8 heat → one temperature step.
- Temperature ends at +8°C, oxygen at 14%, oceans at nine. The game ends at the end of the generation in
  which all three are complete, after production and a final greenery conversion.
- Each greenery scores 1; each city scores 1 per adjacent greenery, whoever owns it.
- Milestones cost 8 M€ and score 5; normally three can be claimed in total.
- Awards cost 8 / 14 / 20 M€ to fund; normally three can be funded. First scores 5, second 2. Funding
  doesn't guarantee winning.
- Steel pays 2 M€ towards building cards; titanium pays 3 towards space cards. Neither is general cash.
- An ordinary greenery must go next to one of your own tiles when possible. Ordinary cities can't go
  next to other cities.

### Rules that commonly cause bad decisions

- Event tags count when the event is played, then stop counting as persistent tags (milestones, awards
  and requirements ignore them).
- The app may let you raise a parameter after it is maxed, but that part gives no increase and no TR.
- The game log doesn't record every triggered resource change. Trust the resource display.
- A card's own tag doesn't count toward its own requirement. A production decrease that looks optional
  often isn't.
- A city on a reserved off-map area has no neighbours, so it scores no greenery points (it still counts
  as a city for cards that count cities).
- If the server rejects a move, read the exact reason instead of repeating the move.
- A **wild tag** can supply a tag for an action or milestone claim, but doesn't count for awards or
  end-game multipliers. A **clone tag** (Pathfinders) permanently becomes the tag you choose when played.
  A **wild resource** is a choice of resource, not a tag.

---

## 3. Settings to check at the start of every game

Read these from the game itself. Don't assume them.

| Setting | Why it matters |
|---|---|
| Player count | Game length, award competition, how contested milestones are |
| Map | Special spaces and placement rules; `tfm` lists each space's bonuses |
| Expansions | Venus, Colonies, Prelude, Turmoil, Ares, Pathfinders, Underworld, etc. change what's valuable |
| Draft variant | Whether you pass cards between players during research |
| Milestones and awards | Often random, sometimes fan-made. `tfm` prints each requirement the first time |
| Colonies in play | Only the tiles shown can be traded with or settled |
| Banned or replaced cards | A card name can appear as its **Ares replacement version**, with its own text: read it |
| Venus | Whether Venus must be completed to end the game, and whether the alternative Venus board is on |
| Clock penalty (Escape Velocity) | Thinking time can cost VP |

**Clock penalty:** the allowance is `threshold + seconds per action × actions taken`; past it you lose
the stated VP for each full penalty period. `tfm` prints clock, allowance and penalty every turn. Your
first action isn't timed; thinking on your turn is.

---

## 4. The opening: choose a package

Judge corporation, preludes and starting cards together. For each serious option, sketch a
generation-1 sequence and a generation-2 goal, and check the cash left after buying cards, prelude
costs, required first actions, available metal and placement legality. A combination you can't pay for
is not an opening.

Compare packages on immediate usable economy, synergy with the cards actually offered, milestone timing
and cash to claim, access to trades and placements, flexibility if a rival takes your target, and a
credible path to points at the table's pace.

A corporation whose effect fires on **any** player's action is often stronger than one that only
rewards your own plays. Poseidon (+1 M€ production per colony anyone places) reached +11 and +19 M€
production in two games; Aphrodite plus a second card paying for Venus steps returned 52 M€. Check the
opposite case too: a corporation action needing a resource you won't produce may never fire.

Preludes that give early resources can unlock a sequence production alone can't pay for, but cash that
buys nothing useful can be worse than lasting production. A prelude placing a colony with a double
bonus on an ocean-placing tile gave two oceans (2 TR plus placement bonuses) in generation 1.

Keep starting cards you can realistically play. Don't leave your corporation unable to act in
generation 1. Cards whose value grows with the generation number (e.g. Flat Mars Theory) are worth
holding for a couple of generations.

---

## 5. Drafting and buying

**Draft** for cards that fix a current bottleneck, enable an affordable high-value sequence, secure a
scoring race, or give efficient points within the remaining game. Denial is worth a pick when the rival
is both likely to use the card and would gain a lot; don't pay 3 M€ to keep a pure denial pick.

**Buying test**, for each card:

- When will I play it, and what pays for it?
- How many useful activations or production phases are left?
- What resource, tag, requirement or board condition does it need? For placement restrictions
  (volcanic spaces, spaces next to two oceans), check that a legal space exists and will stay free.
- What other purchase or action does it displace?

Judge the **whole purchase** against your action-phase budget: three reasonable cards can together block
a milestone claim or an award fee. A card in hand is a sunk cost; selling it can be right when the
proceeds complete a better scoring action.

---

## 6. Valuing resources

### Baseline exchange rates

| Unit | Worth | Where the number comes from |
|---|---:|---|
| 1 VP | 5 M€ | Dust Seals: 2 M€ to play + 3 M€ to buy, for 1 VP |
| 1 TR | 8.5 M€ | Release of Inert Gases: 14 M€ + 3 M€ to buy, for 2 TR |
| Heat | ~1 M€ | 8 heat = 1 temperature TR. About 0 once temperature is maxed |
| Plant | ~1.7 M€ | 8 plants = greenery (1 VP + 1 oxygen TR). ~0.6 M€ once oxygen is maxed |
| Steel / titanium | 2 / 3 M€ | Only when you have a matching card to spend it on |
| Card in hand | 3–4 M€ | Roughly its purchase price; less late when it can't be played |
| M€ production | ~1 M€ per remaining usable production phase | The final phase can't fund a normal action |

A TR is 1 VP at the end **and** 1 M€ per remaining production phase, so it's worth more early and about
5 M€ in the last generation. **Card test:** compare total value (VP × 5 + TR × 8.5 + resources +
production) with `cost + 3`. Preludes and corporations have no purchase price. `tfm value` applies these
rates and flags many hidden effects.

Standard projects are worse than these rates (Asteroid: 14 M€ for 1 TR; Greenery: 23 M€ for ~13.5 M€).
They are a ceiling on what to pay when no card does better, and a use for spare final-generation cash.

### Value depends on time

| Resource | Main question |
|---|---|
| M€ | Which specific action does the next unit enable? |
| Steel / titanium | How much can be spent on suitable cards before the game ends? |
| Plants | Will these reach a greenery before attacks or the final conversion? |
| Energy | Is it needed for a trade, a card action or a production cost? Budget each unit once |
| Heat | Are temperature steps, or another explicit heat use, still available? |
| Cards | Is there affordable play value, a scoring count, or only sale value? |
| Tags | Do they unlock a requirement, milestone, award, trigger or multiplier? |
| Card resources | Can a rival's action (Ants, Predators and similar) steal them before they score? |
| Corruption (Underworld) | Will it block an attack, or cancel negative card VP at the end? |

Titanium with nothing left to spend it on is worth much less than cash; the one plant that completes 8
can matter more than several that stay stranded. Count only **spendable** production payouts, and only
the discounts you will actually use. For repeatable actions, count the affordable, useful uses left.

When a rival has a stealing action, spend card resources as soon as they reach a threshold, or block
the attack with corruption. In one game Ants took microbes three times (a fourth was blocked), costing about one TR and a VP.

### Hidden value: what a card triggers, enables, counts toward and denies

Before buying or ranking a card, ask:

- **Who will trigger it?** An effect fed by every player grows with the table. A card gaining plant
  production whenever *anyone* placed a greenery reached +9; Zeppelins paid +5 M€ from rivals' cities.
- **What does it unlock?** A cheap card that completes a threshold, meets a requirement or finds a key
  card can beat an expensive one.
- **Does it add an action?** A free trade, a fleet reuse, or returning events to hand is an extra action.
- **What does it feed?** Cards that put animals, microbes or data onto other cards score through their
  targets.
- **Which tags does it bring?** Count every requirement, milestone, award, planetary track and
  per-tag payout it moves. Terraforming Ganymede (TR per Jovian tag) gave 5 TR after cheap Jovian cards
  were played first.
- **Does it count for an award?** Cheap cards can decide a count-based award late in the game.
- **What does it deny?** A 1 M€ card that removed 2 animal VP from the eventual winner equalled the
  winning margin.
- **Does it cross a bonus threshold?** Global parameters and Pathfinders tracks pay extra at fixed steps
  (oxygen 8% raises temperature; 0°C places an ocean). Follow the chain: one 13 M€ plant event set off
  about five TR, three greeneries and 12 M€ of ocean income.
- **Is cash now worth more than cash later?** Money for a contested action this turn (an ocean while
  oceans remain) beats the same money next generation.
- **What is the payment really worth?** A card paid mostly with otherwise dead titanium is cheaper than
  its listed cost.
- **Does taking the last step deny someone?** Taking the last parameter step strands rivals' saved heat
  or plants and can end a rival's repeatable action early.
- **What does it cost hidden?** A tag can lock you out of a later effect; raising a parameter may pay
  rivals' triggers; track rewards that go to everyone help rivals.
- **How many payouts are left?** Production bought in the last two generations rarely repays its cost.

### Payments

The cost `tfm` shows in a play choice already includes your discounts; `tfm card` shows the printed
cost. `tfm` suggests a payment (metal first); override it, e.g. `play 1.4 mc=4,steel=3`, to save a
scarce metal you need for an action with no cash alternative.

---

## 7. Milestones and awards

### Milestones: check every turn

`tfm` lists every milestone with your score, the best rival's, and `<<< YOU CAN CLAIM` when you qualify.
Recheck after **every** play that changes tags, production, TR, hand size, colonies or tiles: one player
qualified on the spot and never noticed.

Milestones go early. In four-player games all three were gone by generation 5, the first sometimes in
generation 1. By generation 2 or 3, pick the milestone you will race and play the cards that move it
first. In a race, count rivals' tiles and tags every turn and save the cost of the last tile plus the
8 M€ claim before anything optional; one Mayor race was lost by a single action after 9 M€ went on a minor
trade. Qualifying is not scoring: claim a contested milestone as soon as you can.

### Awards: project the finish

Before funding, estimate your final score on the award and each serious rival's reachable score.

- **Fund counts your engine keeps raising** (production, cards played, tiles), not stock you will spend.
  Banker funded in generation 1 on a 6-to-2 lead and Innovator funded in generation 8 and padded with
  cheap cards won a game; an Industrialist lead built on steel stock vanished when the steel was spent.
- **A thin lead in a count anyone can raise cheaply is weak.** Players have funded awards they led and
  scored nothing after rivals overtook them, once by padding a cheap card type late.
- **Don't wait too long on a wide lead.** One player led an award 7 tiles to 2 and never funded it;
  another led 16 to 4 but had 3 M€ when the last slot was open. Both scored 0. While a slot is open and
  you hold a lead rivals can't close, keep the fee in reserve.
- Letting a rival fund an award you will win can be better than paying for it yourself; funding early
  locks the cheaper slot. Re-check standings before spending resources an award counts.

---

## 8. The map and game pace

### Judge a placement before choosing it

For each candidate space consider printed bonuses, ocean adjacency (2 M€ each), special-tile bonuses,
adjacency rewards paid to rivals, hazard costs and placement fees, city scoring, award progress, room to
expand, and which spaces you open or deny. `tfm` lists each legal space with its bonuses, token and
neighbours; `tfm board` shows every tile.

A city next to several greeneries is efficient points and denial; one surrounded by spaces you can't
fill is weak. Greeneries next to a rival's city can still be worth it, but count the points you give
away. Identify open city sites beside your greeneries before spending your last cash: one rival built
there after the owner passed and won by one point.

**Get on-map tiles down early.** Players whose first city or greenery came in generation 6 or later
scored 5–8 board points against 10–21 for the others.

### Ending versus extending

Track the slowest global parameter, and watch rivals' cash for standard projects as well as their
production. When two parameters are close to finished, a burst of greeneries and oceans can finish them
in one generation: in one game oxygen and oceans both finished in generation 8, two generations earlier
than the pace suggested. Switch to points then, not when an estimate says so. Maxing temperature doesn't
end the game, but immediately makes heat nearly worthless.

Estimate what one more generation is worth to you and to your strongest rival. If they gain more from
repeated scoring actions, speeding up the end can be right; if you gain more, don't close the last
parameter unless the immediate points make up for it.

---

## 9. Expansions

### Colonies

A standard trade costs 9 M€, 3 energy or 3 titanium; a colony costs 17 M€. Normally each fleet trades
once per generation and each tile can be traded with once per generation. `tfm` lists each trade's
current reward. **You get the trade reward only**: the listed colony bonus goes to each colony owner on
the tile (you included only if you own one there).

Judge a trade by its usable reward minus the real cost of what you paid with; titanium or energy with no
other use is cheap. A colony is worth its placement reward plus owner bonuses that rivals will actually
trigger. Read community colonies' current app text: Titania gave 5 VP for the first colony and 3 for
the second, so a 17 M€ colony beat a 23 M€ greenery late in the game.

### Ares

Hazards cost production when you place next to them and change as parameters advance; covering one costs
M€ and gives TR. Some spaces charge a placement fee (one greenery cost 8 M€). Bonus tiles pay whoever
places next to them and their owner. An animal placement bonus is lost if you have no animal card in
play. Ocean upgrades don't place a new ocean or give ocean TR. Treat each placement as a complete
transaction.

### Pathfinders

Planetary tags (including event tags when played) advance the matching tracks; requirement modifiers
don't affect them. Rewards may go to the triggering player, to everyone or to the tag leader. Look at the
next threshold before choosing card order: crossing a reward now can be worth a lot, but a reward that
goes to everyone may help a rival.

### Underworld

Excavating costs 7 M€ (steel allowed) and usually has to be next to your tiles or excavations. An
excavation marker isn't a surface tile: no ocean adjacency, no greenery or city placement. Placing a
tile removes the token beneath it. Compare a blind dig with a concrete alternative; a known token that
completes a threshold is easier to value.

Corruption has two uses. It blocks qualifying attacks (damage or theft) against you, and at the end of
the game each corruption you still hold cancels 1 VP of negative card points (shown as "Underworld
Corruption Bribe" in the breakdown). So value corruption by your negative-VP cards: one player's 3
corruption recovered 3 of their 4 negative VP, while a rival with −2 VP and no corruption kept the full
penalty. Corruption beyond your negative card VP is only worth its blocking use. Before paying for an
attack, check whether the target can block it or halve the loss. Some printed rules aren't implemented
in the app.

### Venus

Check whether Venus must be completed to end the game. Air Scrapping gets 1 M€ off per persistent Venus
tag (up to 5); on the alternative board each step beyond 16% also gives a chosen resource, and the 30%
step a **wild resource, not a wild tag**. There is no general heat-to-Venus conversion. When a prompt
asks for a resource, choose the one that completes your best sequence.

### Prelude, Turmoil, Moon and others

Preludes change starting cash, tags, production and immediate options; a Prelude 2 prelude with an
action is not a blue project card. An unplayable prelude gives 15 M€ under the app's rules. Turmoil and
Moon inputs work generically in `tfm` but are untested: read their rules before planning.

---

## 10. Endgame procedure

When the game may end this generation, stop engine planning and compare concrete scoring bundles.

1. List points available now: TR still gainable, card VP, resource-card thresholds, cities, greeneries,
   colony or track rewards, awards.
2. Project final plants (stock + production + placement rewards). Count complete greeneries.
3. Take contested opportunities first: milestone claims, city sites, trade slots, the last parameter steps.
4. Use worthwhile once-per-generation actions, including free trades for card resources.
5. Sell dead cards when the proceeds enable a better action.
6. Spend leftover cash on standard projects that still score: Air Scrapping while Venus is open, a
   greenery next to your city, a colony with VP.
7. Check the whole payment sequence, including triggered resources, and the projected clock penalty.
8. Pass only after an explicit scan for missed points and useful actions.

Cash shown after final production is mostly final income. Cash left during the action phase that could
have bought points deserves scrutiny.

---

## 11. Lessons from past games

Six seat reports from five four- and five-player games with all §9 expansions except Turmoil and Moon,
clock penalty on. The lessons are folded into the sections above; the results show which categories
decided games.

| Result | TR | What decided it |
|---|---:|---|
| Win, 85–84 | — | Early economy (Allied Bank copied by Double Down, +8 M€ production), three early milestones, colonies, award timing and fleet reuse |
| Win, 84–82 | 45 (highest) | Poseidon to +19 M€ production; Banker (generation 1) and Innovator (generation 8) for 10 award VP; TR from late bursts. Despite 0 milestones and 8 board points |
| 2nd, 82 vs 84 | 32 (lowest) | Best board (21) and two milestones, but its only award lead was steel stock that got spent |
| 4th, 75 vs 84 | 35 | Couldn't pay the last award fee while leading Industrialist 16 to 4; lost Mayor by one action; production bought after the pace accelerated |
| 4th, 70 vs 97 | 40 | Biggest income (+38 M€) but kept buying production to the end; first city off-map; no greenery until the last generation |
| 4th, 63 vs 93 | 44 (highest) | 0 city points, a missed claimable milestone, a funded award lost, heat production after temperature was maxed, −4 clock penalty |

Recurring patterns: awards and milestones decided every close game; TR alone never did; board
points were the biggest gap for players who started their ground game late; and production bought late
rarely paid back.

---

## 12. Turn routine with `tfm`

On each `tfm turn`:

1. Scan `SINCE YOUR LAST LOOK` for what opponents did, and `MILESTONES` / `AWARDS` for anything you or a
   rival can now claim or fund.
2. Glance at the clock line.
3. Pick the action. If it creates a choice that could change your second action (a draw, a placement),
   decide the second after seeing the result. Choice ids renumber after every action, so never chain two
   `play` commands without reading the list `tfm` prints in between.
4. Keep brief notes between turns: target milestones, reserved cash, planned city sites, estimated
   generations left.

Keep reasoning short on routine turns. A notes template, if you want one or need to hand the game over:

```yaml
generation: ?
estimated_generations_left: ?
plan: ?                     # main scoring routes
reserved: ?                 # cash/resources held for a specific action
milestone_targets: []
award_view: ?               # which funded awards you expect to win or lose
city_sites: []              # spaces worth a city later
final_greenery_projection: ?
strongest_rival_and_threat: ?
```

Unknown means unknown. Don't fill gaps with plausible numbers.

---

## Sources

When this guide and the live app disagree, the app wins.

- Base rulebook: https://fryxgames.se/wp-content/uploads/2023/04/TMRULESFINAL.pdf
- App FAQ: https://github.com/terraforming-mars/terraforming-mars/wiki/FAQ
- Detailed rules FAQ (unofficial): https://github.com/terraforming-mars/faq/wiki
- Prelude rulebook: https://cdn.1j1ju.com/medias/6e/a5/22-terraforming-mars-prelude-rulebook.pdf
- Alternative Venus board: https://github.com/terraforming-mars/terraforming-mars/wiki/Alternative-Venus-Board
- Pathfinders: https://github.com/terraforming-mars/terraforming-mars/wiki/Pathfinders
- Ares: https://github.com/terraforming-mars/terraforming-mars/wiki/Ares
- Underworld: https://github.com/terraforming-mars/terraforming-mars/wiki/Underworld
- Escape Velocity, variants and options: the `EscapeVelocity`, `Variants` and `GameOptions` pages of the app wiki
- Card list: https://terraforming-mars.herokuapp.com/cards
