import { deriveAesKey, openSealed } from './privacy';
import { validateTitleRows, type PaperTitle } from './topics';

/** Per-researcher encrypted paper titles (public/data/topics/titles/, see backend/topics/encrypt_titles.py).
 *  The key is derived once at unlock and kept in memory; each researcher's file is fetched and opened
 *  only when that researcher is shown. Nothing decrypted is written to storage. */
export type TitleVault = { key: CryptoKey; aad: string; base: string; gzip: boolean };
type KeyFile = { version: number; iterations: number; salt: string; aad: string; encoding?: string; check: { nonce: string; ciphertext: string } };
type Sealed = { nonce: string; ciphertext: string };

const bytes = (text: string) => new TextEncoder().encode(text);

/** null when the release has no title files or the password does not open them. */
export async function openTitleVault(password: string, base: string): Promise<TitleVault | null> {
  const response = await fetch(`${base}key.json`).catch(() => null);
  if (!response?.ok) return null;
  try {
    const meta = await response.json() as KeyFile;
    if (meta.version !== 2 || typeof meta.aad !== 'string') return null;
    const key = await deriveAesKey(password, meta.salt, meta.iterations);
    const gzip = meta.encoding === 'gzip';
    if (await openSealed(key, meta.check.nonce, meta.check.ciphertext, bytes(`${meta.aad}check`), gzip) !== 'ok') return null;
    return { key, aad: meta.aad, base, gzip };
  } catch { return null; }
}

export async function readTitles(vault: TitleVault, id: string): Promise<PaperTitle[] | null> {
  if (!/^P-[A-Z2-7]{10}$/.test(id)) return null;
  const response = await fetch(`${vault.base}${id}.json`).catch(() => null);
  if (!response?.ok) return null;
  try {
    const sealed = await response.json() as Sealed;
    return validateTitleRows(await openSealed(vault.key, sealed.nonce, sealed.ciphertext, bytes(`${vault.aad}${id}`), vault.gzip));
  } catch { return null; }
}
