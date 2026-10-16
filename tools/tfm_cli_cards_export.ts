// Exports each card's declarative effects (behavior, action, TR hint, VP rule) and the Pathfinders
// planetary track rewards for the tfm Python CLI (`tfm value`).
// Cards whose play or action is hand-written are flagged so the CLI knows its numbers are partial.
import * as fs from 'fs';
import {ALL_MODULE_MANIFESTS} from '../server/cards/AllManifests';
import {CardManifest} from '../server/cards/ModuleManifest';
import {Card} from '../server/cards/Card';
import {ICard} from '../server/cards/ICard';
import {PLANETARY_TRACKS} from '../common/pathfinders/PlanetaryTracks';

const base = Card.prototype as unknown as Record<string, unknown>;

function overrides(card: ICard, method: string): boolean {
  const own = (card as unknown as Record<string, unknown>)[method];
  return own !== undefined && own !== base[method];
}

/** Names of the card's own event hooks (onCardPlayed, onTilePlaced, ...): it reacts to play during the game. */
function triggerNames(card: ICard): Array<string> {
  const names = new Set<string>();
  let proto = Object.getPrototypeOf(card);
  while (proto && proto !== Card.prototype && proto !== Object.prototype) {
    for (const key of Object.getOwnPropertyNames(proto)) {
      if (/^on[A-Z]/.test(key) && key !== 'onDiscard') names.add(key);
    }
    proto = Object.getPrototypeOf(proto);
  }
  return [...names];
}

const out: Record<string, unknown> = {};
for (const manifest of ALL_MODULE_MANIFESTS) {
  const groups: Array<CardManifest<ICard>> = [
    manifest.projectCards, manifest.corporationCards, manifest.preludeCards, manifest.ceoCards,
  ];
  for (const group of groups) {
    for (const [name, spec] of CardManifest.entries(group)) {
      if (spec.instantiate === false) continue;
      const card = new spec.Factory();
      const props = (card as unknown as {properties?: Record<string, unknown>}).properties ?? {};
      out[name] = {
        behavior: card.behavior,
        action: props.action,
        tr: card.tr,
        vp: card.victoryPoints,
        cardDiscount: card.cardDiscount,
        resourceType: card.resourceType,
        firstAction: (card as unknown as {firstAction?: unknown}).firstAction,
        bespokePlay: overrides(card, 'bespokePlay'),
        bespokeAction: typeof (card as unknown as Record<string, unknown>).action === 'function' && props.action === undefined,
        triggers: triggerNames(card),
      };
    }
  }
}
fs.writeFileSync(process.argv[2], JSON.stringify({cards: out, planetaryTracks: PLANETARY_TRACKS}));
console.log(`exported ${Object.keys(out).length} cards`);
