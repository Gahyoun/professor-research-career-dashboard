import { openSealed } from './privacy';
import type { TitleVault } from './titleVault';

export type AbaPaper = { id: number; year: number; title: string };
export type AbaPath = { first: AbaPaper; middle: AbaPaper; last: AbaPaper };
type AbaShard = { works: Record<string, unknown>; researchers: Record<string, unknown> };
const cache = new WeakMap<TitleVault, Map<string, Promise<AbaShard>>>();

function decode(raw: unknown): AbaShard {
  if (!raw || typeof raw !== 'object') throw new Error('Invalid ABA bundle');
  const bundle = raw as { version?: unknown; works?: unknown; researchers?: unknown };
  if (bundle.version !== 1 || !bundle.works || typeof bundle.works !== 'object' ||
      !bundle.researchers || typeof bundle.researchers !== 'object') throw new Error('Invalid ABA bundle');
  return { works: bundle.works as Record<string, unknown>, researchers: bundle.researchers as Record<string, unknown> };
}

async function loadShard(vault: TitleVault, shard: string) {
  const response = await fetch(`${vault.base}../aba-v1/${shard}.json`);
  if (!response.ok) throw new Error('Could not load ABA bundle');
  const { nonce, ciphertext } = await response.json() as { nonce: string; ciphertext: string };
  const aad = new TextEncoder().encode(`topic-aba-v1:${shard}`);
  return decode(await openSealed(vault.key, nonce, ciphertext, aad, true));
}

function paper(id: unknown, works: AbaShard['works']): AbaPaper | null {
  if (typeof id !== 'number' || !Number.isSafeInteger(id) || id <= 0) return null;
  const row = works[id];
  if (!Array.isArray(row) || !Number.isInteger(row[0]) || row[0] < 1800 || row[0] > 2025 ||
      typeof row[1] !== 'string' || !row[1].trim()) return null;
  return { id, year: row[0] as number, title: row[1] };
}

export async function readAbaPaths(vault: TitleVault, researcher: string): Promise<AbaPath[]> {
  if (!/^P-[A-Z2-7]{10}$/.test(researcher)) return [];
  let byShard = cache.get(vault);
  if (!byShard) {
    byShard = new Map();
    cache.set(vault, byShard);
  }
  const shard = researcher[2];
  let pending = byShard.get(shard);
  if (!pending) {
    pending = loadShard(vault, shard);
    byShard.set(shard, pending);
    void pending.catch(() => byShard.delete(shard));
  }
  const { works, researchers } = await pending;
  const rows = researchers[researcher];
  if (!Array.isArray(rows)) return [];
  return rows.flatMap(row => {
    if (!Array.isArray(row) || row.length !== 3) return [];
    const first = paper(row[0], works), middle = paper(row[1], works), last = paper(row[2], works);
    return first && middle && last && first.year < middle.year && middle.year < last.year &&
      middle.year - first.year <= 3 ? [{ first, middle, last }] : [];
  });
}
