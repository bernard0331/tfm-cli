// Exports board adjacency and enum names for the tfm Python CLI.
import * as fs from 'fs';
import {GameSetup} from '../server/GameSetup';
import {DEFAULT_GAME_OPTIONS} from '../server/game/GameOptions';
import {BoardName} from '../common/boards/BoardName';
import {SeededRandom} from '../common/utils/Random';
import {SpaceBonus} from '../common/boards/SpaceBonus';
import {TileType, tileTypeToString} from '../common/TileType';
import {SpaceType} from '../common/boards/SpaceType';

const boards: Record<string, unknown> = {};
for (const name of Object.values(BoardName)) {
  const board = GameSetup.newBoard({...DEFAULT_GAME_OPTIONS, boardName: name}, new SeededRandom(1));
  const spaces: Record<string, unknown> = {};
  for (const s of board.spaces) {
    if (s.spaceType === SpaceType.COLONY) continue;
    spaces[s.id] = {x: s.x, y: s.y, adj: board.getAdjacentSpaces(s).map((a) => a.id)};
  }
  boards[name] = spaces;
}
const bonus: Record<number, string> = {};
for (const [k, v] of Object.entries(SpaceBonus)) if (typeof v === 'number') bonus[v] = k.toLowerCase();
const tiles: Record<number, string> = {};
for (const v of Object.values(TileType)) if (typeof v === 'number') tiles[v] = tileTypeToString[v as TileType];
fs.writeFileSync(process.argv[2], JSON.stringify({boards, spaceBonus: bonus, tileType: tiles}));
