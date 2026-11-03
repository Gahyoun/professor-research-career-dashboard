export type EncryptedNames = {
  iterations: number; salt: string; nonce: string; aad: string; ciphertext: string;
};
function b64(value: string) {
  return Uint8Array.from(atob(value), char => char.charCodeAt(0));
}

/** PBKDF2-SHA256 → AES-256-GCM, shared by every encrypted bundle in public/data. */
export async function decryptJson(password: string, payload: EncryptedNames): Promise<unknown> {
  const material = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: b64(payload.salt), iterations: payload.iterations, hash: 'SHA-256' },
    material, { name: 'AES-GCM', length: 256 }, false, ['decrypt'],
  );
  const plain = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: b64(payload.nonce), additionalData: b64(payload.aad), tagLength: 128 },
    key, b64(payload.ciphertext),
  );
  return JSON.parse(new TextDecoder().decode(plain));
}

export async function decryptNameMap(password: string, payload: EncryptedNames) {
  const names = await decryptJson(password, payload);
  if (!names || typeof names !== 'object' || Array.isArray(names) || Object.entries(names).some(([id, name]) => !/^P-[A-Z2-7]{10}$/.test(id) || typeof name !== 'string')) throw new Error('Invalid name map');
  return names as Record<string, string>;
}
