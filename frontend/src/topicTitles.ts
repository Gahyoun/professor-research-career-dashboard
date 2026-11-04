// Paper titles for the topic page, decrypted in memory after unlock only.
// Sharded release: data/topics/titles/key.json (salt, iterations, AAD) + one AES-GCM shard per
// researcher, so the key is derived once and only opened researchers are fetched.
// Older releases ship one data/topics/encrypted_titles.json bundle.
import { decryptJson, decryptWithKey, deriveKey, type EncryptedNames } from './privacy';
import { validatePaperTitles, type EncryptedPaperTitles } from './topics';

export type TitleRows = EncryptedPaperTitles[string];
export type TopicTitleSource = (id: string) => Promise<TitleRows | null>;
type KeyHeader = { salt: string; iterations: number; aad: string };
type Shard = { nonce: string; ciphertext: string };
const SAFE_ID = /^[A-Za-z0-9-]+$/;

export async function openTopicTitles(password: string, base: string): Promise<TopicTitleSource | null> {
  const keyResponse = await fetch(`${base}data/topics/titles/key.json`).catch(() => null);
  if (keyResponse?.ok) {
    const header = await keyResponse.json() as KeyHeader;
    if (typeof header.salt !== 'string' || typeof header.aad !== 'string' || typeof header.iterations !== 'number') return null;
    const key = await deriveKey(password, header.salt, header.iterations);
    const cache = new Map<string, Promise<TitleRows | null>>();
    return id => {
      if (!SAFE_ID.test(id)) return Promise.resolve(null);
      let pending = cache.get(id);
      if (!pending) {
        pending = fetch(`${base}data/topics/titles/${id}.json`)
          .then(r => r.ok ? r.json() as Promise<Shard> : null)
          .then(async shard => shard ? validatePaperTitles({ [id]: await decryptWithKey(key, shard.nonce, header.aad, shard.ciphertext) })[id] ?? null : null)
          .catch(() => null);
        cache.set(id, pending);
      }
      return pending;
    };
  }
  const legacy = await fetch(`${base}data/topics/encrypted_titles.json`).catch(() => null);
  if (!legacy?.ok) return null;
  const all = validatePaperTitles(await decryptJson(password, await legacy.json() as EncryptedNames));
  return id => Promise.resolve(all[id] ?? null);
}
