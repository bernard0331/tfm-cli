# Terraforming Mars: strategy and rules context for agents

Context for an AI agent playing a seat with `tfm` (see [AGENT_INSTRUCTIONS.md](../AGENT_INSTRUCTIONS.md)).
It gives a strategic framework, rules reminders that commonly trip players up, notes on the
expansions, and lessons from past games. Read it once at the start of a game. You don't need to
re-read it every turn.

It is **not** a card database or proof of optimal play. When a card interaction is unusual, the exact
card text (`tfm card "<name>"`), the live game settings, and the choices `tfm` offers you decide.
Never claim to have memorized every card, and never carry resources, coordinates or plans over from
a previous game.

---

## Ten priorities

1. Read the actual setup from your first `tfm turn`: player count, map, expansions, milestones,
   awards, colonies, and whether the clock penalty is on.
2. Track stock and production separately. Note which card actions you've used and which fleets are free.
3. Estimate how many generations are left from **every** player's ability to finish the global parameters,
   and switch from buying production to buying points about two generations before that end.
4. After every card or tile, recheck **all** unclaimed milestones, not just the ones you were aiming for.
5. Keep cash in reserve for a milestone claim or contested opportunity before spending on optional development.
6. Drafting, buying and playing are three separate decisions. A good draft pick doesn't have to be worth buying.
7. Only place tiles on the spaces `tfm` lists, and read each space's bonus and neighbours before choosing.
8. Value a resource by its remaining uses. Heat after temperature is maxed is not automatic TR.
9. Before passing, look for unused scoring actions, trades, plant thresholds, milestones, awards and hand sales.
10. Keep routine turns fast. Save long thinking for the opening, award funding and the endgame.

---

## 1. Strategic model

Terraforming Mars is a competition over **time, capital, scoring opportunities and access**. Your
opponents help decide when your investments stop paying. An engine that needs three more
generations is weak if the table can end the game this generation.

Keep two projections:

- **Economic:** what can I afford and activate before the next production phase?
- **Scoring:** where will my final points come from if the game ends this generation, next
  generation, or the one after?

Break the scoring projection into TR, milestones, awards, greeneries, cities, card and resource
points, expansion points, and penalties (including the clock penalty, §3). `tfm` prints your current
VP breakdown every turn. A weak category is fine if another route makes up for it; a balanced score
sheet is not a goal in itself.

For any candidate action, ask:

> What does this add to my likely final score, what does it enable, what does it give or deny the
> strongest rival, and what better action does its cost rule out?

Don't turn that into a fake precise formula. Hidden hands, unknown draws and uncertain game length
call for ranges and judgement.

### Main strategic directions

| Direction | When it is attractive | Main failure mode |
|---|---|---|
| Fast terraforming | Efficient heat, plants and events, and a lead that benefits from an early finish | Helping close the game while a rival scores more efficiently elsewhere |
| Economy and card engine | Early discounts or card draw, reliable things to spend on, enough generations left | Investing after the payback window has closed |
| Ground game | Plant supply, good placements, viable city sites, map-related scoring | Expensive empty cities, or greeneries that feed opponents' cities |
| Space/Jovian | Titanium supply, strong space cards, multipliers you can support | Collecting tags or metal with no affordable way to score them |
| Resources on cards | Repeatable animals, floaters, microbes or data with a good conversion | Buying a slow action too late, or having no card to put resources on |
| Colonies and trade | Profitable reachable colonies, a cheap way to pay for trades, useful owner bonuses | Assuming an attractive trade will still be there on your turn |

Most winning positions mix directions. Pick an initial emphasis, then adapt to the cards you
actually get and the opponents you actually face.

---

## 2. Rules baseline

Normal multiplayer defaults; cards, maps and variants can override them.

- Each turn you take one or two actions; passing ends your participation for the generation.
- Research cards cost 3 M€ each to keep, separately from their play cost.
- Each blue-card action can normally be used once per generation.
- Production gives resources; M€ income includes your TR. Leftover energy becomes heat before new
  energy is produced.
- Standard conversions: 8 plants → a greenery; 8 heat → raise temperature one step.
- Temperature ends at +8°C, oxygen at 14%, oceans at nine. The game normally ends at the end of the
  generation in which all three are complete, after production and a final greenery conversion.
- TR scores at the end. Each greenery scores 1; each city scores 1 per adjacent greenery, whoever owns it.
- Milestones cost 8 M€ and score 5; normally only three can be claimed in total.
- Awards cost 8 / 14 / 20 M€ to fund; normally three can be funded. Funding doesn't guarantee winning.
  First scores 5, second scores 2, and ties have special handling.
- Steel normally pays 2 M€ towards building cards; titanium pays 3 towards space cards. Neither is
  general cash.
- An ordinary greenery must go next to one of your own tiles when possible. Ordinary cities can't go
  next to other cities. Special placements may differ.

### Rules that commonly cause bad decisions

- Event tags count when the event is played, then stop counting as persistent tags.
- The app may let you take a parameter-raising action after that parameter is maxed, but that part
  gives no increase and no TR.
- The game log doesn't record every triggered resource change. Trust the resource display.
- Check requirements and mandatory costs before playing. A card's own tag doesn't count toward its
  own requirement. A production decrease that looks optional often isn't.
- A city placed on a reserved off-map area (some space cities do this) has no neighbouring spaces, so
  it scores no greenery points. It still counts as a city for cards that count cities in play.
- If the server rejects a move, read the exact reason instead of repeating the move.

**Wild tag, clone tag and wild resource are different things:**

- A **wild tag** in play can supply a tag for an action, including claiming a milestone. It does
  **not** count for awards or end-game multipliers, and it doesn't trigger tag-specific effects just
  by being played.
- A **clone tag** (Pathfinders) permanently becomes the planetary tag you choose when it's played.
  The choice can trigger play effects, but can't retroactively discount the payment already made.
- A **wild resource** is a choice of resource, not a tag. This matters at the top of the
  Alternative Venus track.

---

## 3. Settings to check at the start of every game

Read these from the game itself. Don't assume them.

| Setting | Why it matters |
|---|---|
| Player count | Game length, award competition, and how contested milestones are |
| Map | Special spaces and placement rules; `tfm` lists each space's bonuses |
| Expansions | Venus, Colonies, Prelude, Turmoil, Ares, Pathfinders, Underworld, etc. change what's valuable |
| Draft variant | Whether you pass cards between players during research |
| Milestones and awards | Often random, sometimes fan-made. `tfm` prints each one's requirement the first time |
| Colonies in play | Only the tiles actually shown can be traded with or settled |
| Banned or replaced cards | A banned card's name can still appear as its **Ares replacement version**, with its own text: read it |
| Venus | Whether Venus must be completed to end the game, and whether the alternative Venus board is on |
| Clock penalty (Escape Velocity) | Thinking time can cost VP; see below |

### Clock penalty (Escape Velocity)

When on, each player gets a time allowance: `threshold + (seconds per action × actions taken)`.
Past the allowance you lose VP for each full penalty period:

```
penalty = floor((clock − allowance) / period) × VP per period   (when positive)
```

For example, with a 45-minute threshold, 2 seconds per action, and −1 VP per 2 minutes: after 117
actions the allowance is 45:00 + 3:54 = 48:54. A clock of 58:18 is 9:24 over, which is four full
periods, or −4 VP.

`tfm` prints your clock, allowance and current penalty every turn. Your first action of the game is
not timed. Time spent thinking on your turn counts, so keep routine turns short.

---

## 4. The opening: choose a package

Judge corporation, preludes and starting cards together. A corporation's reputation matters less than
what the whole opening can actually do.

For each serious option, sketch a generation-1 sequence and a plausible generation-2 goal. Check the
cash left after buying cards, prelude costs, required first actions, available metal and placement
legality. A beautiful combination you can't pay for is not an opening.

Compare packages on:

1. Immediate economy and usable resources.
2. Synergy with the cards you were actually offered, without counting on future draws.
3. Milestone timing and the cash to claim.
4. Access to good trades, placements and scarce slots.
5. Flexibility if an opponent takes the opportunity you wanted.
6. A credible path to final points at the table's likely pace.

A corporation whose effect fires on **any** player's action is often stronger than one that only
rewards your own plays. In one game Poseidon (+1 M€ production per colony anyone placed) reached
+11 M€ production, and Aphrodite together with a second card that pays for Venus steps returned
52 M€, most of it from steps its owner would have raised anyway.
Check the opposite case too: a corporation action that needs a resource you won't produce (for
example a heat-to-TR action with +1 heat production) may never fire.

Preludes that give early resources can unlock a sequence production alone can't pay for. Extra cash
that buys nothing useful can be worse than lasting production. Count tags and placement rewards, but
don't count a reward before you've confirmed when it triggers.

Keep starting cards you can realistically play, or whose exceptional payoff justifies holding them.
Don't buy many speculative cards and leave your corporation unable to act in generation 1.

---

## 5. Drafting and buying

### Draft priorities

Prefer cards that fix a current bottleneck, enable an affordable high-value sequence, secure a
scoring race, or give efficient points within the remaining game. Then consider denial: a strong
rival's multiplier or key enabler can be worth taking even if you won't buy it.

Denial costs you a card for yourself. It's worth it when the opponent is both likely to use the card
and would gain a lot from it. Don't pay 3 M€ to keep a denial pick unless you also want to own it.

### Buying test

For each card:

- When will I play it, and what pays for it?
- How many useful activations or production phases are left?
- What resource, tag, requirement or board condition does it need?
- What other purchase or action does it displace?
- If I can't play it, is there any reason to pay to hold it?

Judge the **whole purchase** against your action-phase budget. Three individually reasonable cards
can together block a milestone claim or an essential engine play. Keep speculative buys rare when
cash is tight.

A card already in hand is a sunk cost. Don't play it just to justify buying it. Selling it can be
right, especially if the proceeds complete a better scoring action.

---

## 6. Valuing resources

### Baseline exchange rates

Use these as the default yardstick for any card or action, then adjust for timing and context:

| Unit | Worth | Where the number comes from |
|---|---:|---|
| 1 VP | 5 M€ | Dust Seals: 2 M€ to play + 3 M€ to buy, for 1 VP |
| 1 TR | 8.5 M€ | Release of Inert Gases: 14 M€ + 3 M€ to buy, for 2 TR |

A TR is worth more than a VP because it is 1 VP at the end **and** 1 M€ of income at every remaining
production phase. Early in the game a TR is worth a bit more than 8.5 M€; in the last generation it is
worth about 5 M€, the same as a VP.

**Card test:** add the 3 M€ purchase price to the play cost. A card is efficient when
`(cost + 3) ÷ VP ≤ 5` for pure VP cards, or `(cost + 3) ÷ TR ≤ 8.5` for pure TR cards. For mixed
cards, total the value (VP × 5 + TR × 8.5 + resources + production) and compare it with `cost + 3`.
Preludes and corporations have no purchase price.

Derived rates for other resources (adjust when the parameter they feed is maxed):

| Resource | Rough worth | Reasoning |
|---|---:|---|
| Heat | about 1 M€ | 8 heat = 1 temperature TR (8.5 M€). About 0 once temperature is maxed |
| Plant | about 1.7 M€ | 8 plants = a greenery: 1 VP + 1 oxygen TR (13.5 M€). About 0.6 M€ once oxygen is maxed (VP only) |
| Steel / titanium | 2 / 3 M€ | Printed rate, and only when you have a matching card to spend it on |
| Card in hand | about 3–4 M€ | Roughly its purchase price; less late in the game when it can't be played |
| M€ production | about 1 M€ per remaining usable production phase | The final production phase can't be spent on a normal action |

`tfm value` applies these rates to the cards in your decision and hand, counts production for the
generations likely left, and flags the hidden effects in the checklist below that it can detect.

Standard projects are worse than these rates (Asteroid: 14 M€ for 1 TR; Greenery: 23 M€ for 13.5 M€
of VP and TR). They set a ceiling on what to pay when no card does better, not the baseline.

### Value depends on time

| Resource | Main question |
|---|---|
| M€ | Which specific action does the next unit enable? |
| Steel / titanium | How much can actually be spent on suitable cards before the game ends? |
| Plants | Will these reach a greenery before attacks or the final conversion? |
| Energy | Is it needed for a trade, a card action or a production cost? |
| Heat | Are temperature steps, or another explicit heat use, still available? |
| Cards | Is there affordable play value, a scoring count, or only sale value? |
| Tags | Do they unlock a real requirement, milestone, trigger or scoring multiplier? |
| Corruption (Underworld) | What defensive, action or scoring use does it have right now? |

Printed metal values are payment rules, not universal values. Titanium with nothing left to spend it
on can be worth much less than cash. The one plant that completes 8 can matter more than several that
stay stranded.

For production, count **spendable** future payouts. A card that costs 10 for M€ production but only
returns 6 M€ before your last chance to spend it needs another benefit to be worth it. Cash from the
final production phase can't fund another normal action, but final plants can still become a greenery.

Discounts need enough future purchases to pay back. A 2 M€ discount used on six later cards saves
12 M€; compare that with the card's cost, its VP, other triggers and the cash you give up. Don't count
hoped-for draws as guaranteed uses.

### Hidden value: what a card triggers, enables, counts toward and denies

Printed VP and the obvious production line are only part of a card's value. In one game the cards
that decided the result mostly scored through effects their text doesn't total up. Before buying or
ranking a card, ask:

- **Who will trigger it?** An effect fed by every player's actions grows with the table, not just
  with you. A card that gained plant production whenever *anyone* placed a greenery reached +9 plant
  production, more than most production cards gave.
- **What does it unlock?** A cheap card that completes a threshold, meets a requirement or finds a key
  card can be worth more than an expensive one. A 5 M€ event that added 5 data to that greenery card
  gave +2 plant production at once; a 2 M€ draw event found its player's best engine.
- **Does it add an action?** A free trade, reuse of a fleet that has already traded, or returning
  played events to hand is an extra action, not just a pile of resources. One card that placed a
  second colony on a tile and traded for free paid back its cost the same turn and raised every
  later trade with that tile.
- **What does it feed?** Cards that put animals, microbes or data onto other cards score through their
  targets. In one game seven of the nine animals on the top-scoring card came from other cards.
- **Which tags does it bring?** Count every requirement, milestone, award and planetary track the tags
  move, not only the card's own effect.
- **Does it count for an award?** Cheap cards can be what decides a count-based award (for example
  most cards of one type) late in the game.
- **What does it deny?** A 1 M€ card that removed 2 animal VP from the eventual winner equalled the
  final winning margin.
- **Does it cross a bonus threshold?** Global parameters pay extra at fixed steps (for example oxygen
  8% raises temperature, and 0°C places an ocean), and Pathfinders tracks pay rewards at fixed steps
  too. Follow the chain: in one game a 13 M€ event gave 14 plants, the greeneries pushed oxygen to
  8%, the temperature bonus let a heat conversion reach 0°C, and that placed the last ocean. One card
  set off about five TR, three greeneries and 12 M€ of ocean-adjacency income.
- **Does a track reward double it?** A cheap card that raised Venus one step also moved its owner's
  Venus planetary track to a reward that raised Venus again: two TR, 4 M€ and two resources for 7 M€.
- **Is cash now worth more than cash later?** Money that pays for a contested action this turn (an
  ocean while oceans remain) beats the same money next generation. An event trading 4 plants nobody
  would have used for 20 M€ funded an ocean and a production card in the same turn.
- **What is the payment really worth?** Value spent resources at their best alternative use, not
  their printed rate. Titanium with only one card left to spend it on costs little; a card paid
  mostly with otherwise dead titanium is cheaper than its listed cost.
- **Does taking the last step deny someone?** Taking the last step of a parameter strands rivals'
  saved resources: one player's last temperature step left another with 14 unusable heat and made a
  third convert 8 heat for nothing. Taking the last ocean ended a rival's repeatable ocean action two
  generations early.
- **What does it cost hidden?** A tag can lock you out of a later effect (one crime tag cost a player
  the 2 TR another card gave to players with none). Raising a global parameter may pay rivals' trigger
  cards, and planetary-track rewards that go to everyone hand each rival a card or cash.
- **How many payouts are left?** Production bought in the last two generations rarely repays its
  cost; one +6 M€ production card arrived for only the final production phase.

### Shared resources

Budget energy before committing to several uses. Three energy set aside for a trade can't also power
a card action. Stock and production are different: lowering production may save today's stock but hurt
next generation's trade.

For repeatable actions, count the **affordable, useful** uses left, not the nominal generations left.
An action that needs a resource you have to buy expensively is weaker than its text suggests.

### Payments

Apply discounts before paying. The cost `tfm` shows in a play choice already includes your
discounts; `tfm card` shows the printed cost. Check which tags allow metal. Keep a scarce metal if you
need it for an action with no cash alternative. Avoid overpaying, but don't hoard metal you have no
better use for. `tfm` suggests a payment (metal first); override it, e.g. `play 1.4 mc=4,steel=3`,
when you want to save metal.

---

## 7. Milestones and awards

### Milestones: check every turn

Every turn `tfm` lists every milestone with your score, the best rival's score, who can claim it, and
`<<< YOU CAN CLAIM` when you qualify. Recheck it after **every** play that changes tags, production,
TR, hand size, colonies or tiles. In one past game a played card qualified the player for a milestone
on the spot, and they never noticed and never claimed it.

Qualifying is not scoring: you have to claim, and later production losses or other actions can take
the qualification away. Claim a contested milestone first when waiting risks losing it, and keep the
8 M€ to do so.

Milestones go early. In one four-player game all three were claimed by generation 5, the first in
generation 1. By generation 2 or 3, pick the milestone you will race, and play the cards that move it
first. Holding a card that advances your best milestone for several generations can cost the race.

### Awards: project the finish

Before funding, estimate your final score on the award and each serious rival's reachable score.
Include known production, likely placements, resource spending and cards already played. An early
lead that's expensive to defend can be a bad investment.

Ask who benefits once the award is funded. Letting someone else pay for an award you can win can be
better than funding it yourself; funding early can also lock in the cheaper slot. Avoid spending
heavily to move from second to first unless the points or denial justify it. Re-check award standings
before spending resources they count.

In one past game a player funded an award they led at the time, for 14 M€, and scored nothing: two
rivals overtook them. A current lead is not protection. In another, a player funded an award for
having the most cards of one cheap type with a narrow lead; a rival padded the count with cheap
cards in the final generations and took first. A thin lead in a count anyone can raise cheaply is
weak.

The opposite mistake costs as much. A player led one award by a wide margin for most of a game
(7 tiles to 2) and never funded it; the slots filled by generation 6 and they finished with 0 award
points. If you have a wide lead that rivals can't easily close, fund it before the slots run out.

---

## 8. The map and game pace

### Judge a placement before choosing it

For each candidate space consider: printed bonuses, ocean adjacency (2 M€ each), special-tile bonuses,
adjacency rewards paid to opponents, hazard costs, city scoring, award progress, room to expand, and
which spaces you open up or deny. `tfm` lists each legal space with its bonuses, underground token and
neighbouring tiles; `tfm board` shows every tile.

Cities aren't automatically good or bad. A city next to several existing greeneries can be efficient
points and denial. An expensive city surrounded by spaces you can't fill is weak. Greeneries next to an
opponent's city can still be worth it, but count the points you give away.

In one past game a player left an obvious city site open beside their own greeneries. An opponent built
there after they passed, scored 3 points, and finished one point ahead. Identify and budget for such
sites before spending your last cash.

### Ending versus extending

Track the slowest global parameter. Maxing temperature doesn't end the game, but it immediately changes
what heat is worth. If oxygen is the last bottleneck, a burst of greeneries can end the game
unexpectedly. Watch opponents' cash for standard projects as well as their production.

Estimate what one more generation is worth to you and to your strongest rivals. If they gain more from
repeated scoring actions than you do, speeding up the end can be right even if your engine is still
growing. If you gain more, don't close the last parameter unless the immediate points make up for it.

Don't assume a fixed game length. Player count, expansions, cards and incentives set the pace. In
one four-player game with Venus, Colonies, Prelude, Pathfinders, Underworld and Ares, all parameters
were done by generation 8, and the oceans during generation 6.

Don't leave your whole ground game for the end. A player whose first city or greenery on the map came
in the last generation finished with 5 board points, against 10 to 19 for the others.

---

## 9. Expansions

### Colonies

A standard trade costs 9 M€, 3 energy or 3 titanium; a standard colony costs 17 M€. Normally each fleet
trades once per generation and each colony tile can be traded with once per generation. Track markers
move and fleets return after production. Colonies with unusual resources activate when matching cards
come into play. `tfm` lists each trade's current reward.

Judge a trade by its usable reward minus the cost of what you paid with, remembering the bonuses it
pays to rival colony owners. Three energy is often cheap, but not if it costs you a better action.
Three titanium isn't automatically worse than cash when the titanium is otherwise stranded.

A colony can be worth it for the immediate placement reward, future owner bonuses, or both. Estimate how
often it will actually be traded with: an owner bonus nobody triggers isn't income. Community colonies
(e.g. Leavitt, Mercury, Hygiea, Titania, Venus, Terra, Iapetus II, Kuiper) can give direct VP or unusual
interactions; read the app's current text rather than older printed versions.

### Ares

Ares adds hazards, adjacency bonuses, replacement tiles and ocean upgrades. Bonus tiles can reward
whoever places next to them and pay their owner. Ocean upgrades don't place a new ocean or give ocean TR.
Covering hazards costs M€ and gives TR; hazards can cost production and change as the global parameters
advance. Treat each placement as a complete transaction. Replacement versions of familiar cards can have
different placement value from the originals.

### Pathfinders

Planetary tags (including event tags when played) advance the matching influence tracks. These aren't
global parameters, and requirement modifiers don't affect them. Rewards may go to the triggering player,
to everyone, or to the tag leader; VP rewards are awarded when the space is reached. The app's rewards can
differ from older printed versions.

Look at the next threshold before choosing card order. A tag can be worth a lot because it crosses a
reward now, but a reward that goes to everyone may help a rival finish an important play.

### Underworld

Identifying reveals an unclaimed resource token. Excavating normally costs 7 M€ (steel allowed) and
usually has to be next to one of your tiles or excavations, unless you have none eligible. Claiming a
token is not excavating. An excavation marker isn't a surface tile: it gives no ocean adjacency income
and doesn't count for city or greenery placement. Placing a tile removes the token or marker beneath it.
Corruption can block qualifying attacks (red-bordered damage or theft) against you. Spending it on bribes
costs VP, so read the actual scoring display rather than assuming one corruption equals one VP. Some
printed rules aren't implemented in the app; don't assume a printed mulligan exists.

Compare excavating with a concrete alternative use of the cash or steel. A known token that completes a
plant threshold or scoring requirement is easier to value than a blind dig.

Before paying extra for a card's attack (removing plants or resources), check whether the target has
corruption to block it or an effect that reduces the loss. In one game a 6-plant removal on the
leader was blocked, and another player's card halved any plants removed from them.

### Venus and the alternative Venus board

Check whether Venus is required to end the game. On the alternative board each step beyond 16% gives a
chosen basic resource, and the 30% step gives a wider resource choice usable on a compatible card:
**a wild resource, not a wild tag**. Air Scrapping gets a 1 M€ discount per persistent Venus tag, up to 5 M€.

There is no general way to convert heat into Venus. Check the actual card action. When a prompt asks
you to choose a resource, choose the one that completes your best sequence, not automatically the metal
with the highest printed value.

### Prelude and Prelude 2

Preludes change starting cash, tags, production and immediate options. Prelude 2 adds ongoing effects
and actions; a prelude with an action is not a blue project card for blue-card counts. An unplayable
prelude gives 15 M€ compensation under the app's rules; check what the app offers.

### Turmoil, Moon and others

If enabled, read their rules before planning. `tfm` supports their inputs generically but has not been
tested with them.

---

## 10. Endgame procedure

When the game may end this generation, stop engine planning and compare concrete scoring bundles.

1. List points available now: TR still gainable, card VP, resource-card thresholds, cities, greeneries,
   colony or track rewards, awards, and variant scoring.
2. Project final plants (stock + production + conversions + placement rewards). Count complete
   greeneries, not abstract plant value.
3. Take contested opportunities before slow ones: milestone claims, city sites, trade slots, the last
   parameter steps.
4. Use worthwhile once-per-generation actions. A card draw can reveal a better use of cash, but isn't
   automatically worth paying for if you're out of money.
5. Recalculate after every meaningful draw or opponent move.
6. Sell dead cards when the proceeds enable a better action. Keep cards and resources that actually score.
7. Check the whole payment sequence, including triggered resources, so each action is affordable when
   you take it.
8. Check the projected clock penalty.
9. Pass only after an explicit scan for missed points and useful actions.

Cash shown after final production isn't proof of wasted money. Most of it is often final income. But
cash left during the action phase that could have bought points deserves scrutiny.

---

## 11. Lessons from past games

Four recorded games (4–5 players, all expansions in §9 except Turmoil and Moon, clock penalty on):

**A win by one point (85–84).** An early economy (Allied Bank copied by Double Down for +8 M€
production) and three early milestones (two claimed in generation 2 after selling a card to complete the
cash) turned into a win through colonies, award timing, fleet reuse and a broad final conversion.
Mistake: an energy-hungry card got only one activation because energy was also needed for trades.

**A loss from fourth place (63 vs 93).** The player had the **highest TR at the table** and still lost
by 30 points:

| Category | Player | Winner | Difference |
|---|---:|---:|---:|
| TR | 44 | 38 | +6 |
| Milestones | 5 | 10 | −5 |
| Awards | 5 | 7 | −2 |
| Greenery | 5 | 6 | −1 |
| Cities | 0 | 15 | −15 |
| Cards/other | 8 | 17 | −9 |
| Time penalty | −4 | 0 | −4 |

What went wrong: no city points; thin card scoring; a milestone race lost because the enabling card was
played too late; a claimable milestone never noticed; heat production kept growing after temperature was
maxed; a funded award scored nothing; an open city site handed to an opponent; and a −4 clock penalty.

**A fourth place in a fast game (70 vs 97, four players, ended after generation 8).** The player
built the biggest income at the table (+38 M€) and still finished last:

| Category | Player | Winner | Difference |
|---|---:|---:|---:|
| TR | 40 | 51 | −11 |
| Milestones | 0 | 0 | 0 |
| Awards | 7 | 9 | −2 |
| Greenery | 1 | 7 | −6 |
| Cities | 4 | 7 | −3 |
| Cards/other | 18 | 23 | −5 |
| Time penalty | 0 | 0 | 0 |

What went wrong: production cards kept being bought until the final generation, so much of the income
never became points; no milestone was attempted, although one was reachable if a card adding
+2 titanium production hadn't been held for three generations; the first city sat on an off-map
reserved area and scored nothing; the only on-map city and the only greenery came in the final
generation; an award the player funded was won by a rival who added cheap qualifying cards late; and
two `play` commands chained in one call played the wrong card after the choice ids renumbered.

What worked for the others: the winner (TR 51, no milestones) used a corporation and a card that paid
out on Venus steps, plus cards that turned extra oceans into animal VP. The runner-up had the
**lowest TR at the table (35)** and finished 2 points behind, through two early milestones (one
claimed in generation 1), a corporation that grew with every colony anyone placed, and two data cards
worth 14 VP. The third-placed player had the best board (19 points) but never funded the award they
led all game.

**Corrections to carry forward:**

- Recheck every milestone after every relevant change.
- A current award lead isn't protection; project rivals' reachable totals.
- Budget the actual number of uses for shared energy.
- Revalue heat the moment temperature is maxed. There is no generic heat-to-Venus conversion.
- Place only on spaces the game lists as legal, using the latest board.
- Budget scoring sites (especially cities next to greeneries) before spending your last cash.
- The clock penalty is real. Keep routine turns short.
- Stop buying production about two generations before the projected end; spend on points instead.
- Pick a milestone to race by generation 2 or 3. In a four-player game they can all be gone by
  generation 5.
- Fund an award you lead by a wide margin before the slots fill. Don't fund one on a thin lead in a
  count rivals can raise cheaply.
- Get on-map tiles down early enough to grow greeneries around them. Off-map cities score no
  adjacency.
- Value cards by what they trigger, enable, count toward and deny, not just printed VP (§6).
- Read the new choice list after every action before submitting another.

---

## 12. Turn routine with `tfm`

On each `tfm turn`:

1. Scan `SINCE YOUR LAST LOOK` for what opponents did, and `MILESTONES` for `<<< YOU CAN CLAIM` or a
   rival about to qualify.
2. Glance at the clock line.
3. Pick the action. If it creates a choice that could change your second action (a draw, a placement),
   decide the second one after seeing the result. Choice ids renumber after every action (an option
   that disappears shifts the ones after it), so never chain two `play` commands without reading the
   list `tfm` prints in between.
4. Keep brief notes of your own plan between turns: target milestones, reserved cash, planned city
   sites, estimated generations left. They help you stay consistent without re-deriving the plan.

Keep reasoning short on routine turns. Spend it on the opening, award funding, and the endgame.

### Notes template

Useful if you want to keep a running summary, or hand the game to another agent:

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
open_questions: []
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
