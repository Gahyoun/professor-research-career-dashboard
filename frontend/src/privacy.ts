export type EncryptedNames = {
  iterations: number; salt: string; nonce: string; aad: string; ciphertext: string;
};
function b64(value: string) {
  return Uint8Array.from(atob(value), char => char.charCodeAt(0));
}

/** PBKDF2-SHA256 key for AES-256-GCM. Non-extractable; lives in memory only. */
export async function deriveAesKey(password: string, salt: string, iterations: number): Promise<CryptoKey> {
  const material = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: b64(salt), iterations, hash: 'SHA-256' },
    material, { name: 'AES-GCM', length: 256 }, false, ['decrypt'],
  );
}

/** AES-256-GCM open of one sealed JSON value; ``aad`` is raw bytes. ``gzip``: the plaintext was compressed before encryption. */
export async function openSealed(key: CryptoKey, nonce: string, ciphertext: string, aad: BufferSource, gzip = false): Promise<unknown> {
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(nonce), additionalData: aad, tagLength: 128 }, key, b64(ciphertext));
  const text = gzip ? await new Response(new Blob([plain]).stream().pipeThrough(new DecompressionStream('gzip'))).text() : new TextDecoder().decode(plain);
  return JSON.parse(text);
}

/** PBKDF2-SHA256 → AES-256-GCM, shared by every single-file encrypted bundle in public/data. */
export async function decryptJson(password: string, payload: EncryptedNames): Promise<unknown> {
  const key = await deriveAesKey(password, payload.salt, payload.iterations);
  return openSealed(key, payload.nonce, payload.ciphertext, b64(payload.aad));
}

export async function decryptNameMap(password: string, payload: EncryptedNames) {
  const names = await decryptJson(password, payload);
  if (!names || typeof names !== 'object' || Array.isArray(names) || Object.entries(names).some(([id, name]) => !/^P-[A-Z2-7]{10}$/.test(id) || typeof name !== 'string')) throw new Error('Invalid name map');
  return names as Record<string, string>;
}
