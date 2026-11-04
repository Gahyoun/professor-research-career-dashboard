#!/usr/bin/env python3
"""Per-researcher encrypted paper titles, venues and DOIs for the topic page (shown after unlock).

  python3 -I backend/topics/encrypt_titles.py --manifest W/manifest.txt \
      --env-file PRIVATE/names.env --out-dir public/data/topics

Layout (all ciphertext; nothing readable without NAMES_PASSWORD):

  titles/key.json   {"version": 2, "kdf", "iterations", "salt", "aad", "encoding": "gzip", "check": {nonce, ciphertext}}
  titles/<id>.json  {"nonce", "ciphertext"}  →  gzip(JSON [{"year", "topic", "title", "venue", "doi"}])

The JSON is gzip-compressed before encryption (ciphertext does not compress, so this is the only
place size can be saved); the page inflates it with DecompressionStream after decrypting.

One PBKDF2-SHA256 key (600k iterations, random salt) is derived once at unlock; each file has
its own random 96-bit nonce and AES-256-GCM additional data ``aad + id`` so a file cannot be
swapped onto another researcher. The page fetches a researcher's file only when that researcher
is open. The password is read from the environment or a private env file and never printed.
"""
import argparse, base64, gzip, hashlib, json, os, secrets, shlex, sys

ITERATIONS = 600_000
AAD = "topic-titles-v2:"
ID_SHAPE = "P-"


def b64(data):
    return base64.b64encode(data).decode()


def read_password(env_name, env_file=None):
    if os.environ.get(env_name):
        return os.environ[env_name]
    if env_file and os.path.exists(env_file):
        for line in open(env_file, encoding="utf-8"):
            parts = shlex.split(line, comments=True)
            if parts and parts[0] == "export":
                parts = parts[1:]
            for part in parts:
                key, _, value = part.partition("=")
                if key == env_name and value:
                    return value
    return None


def normalise_doi(doi):
    doi = (doi or "").strip()
    if doi.lower().startswith("https://doi.org/"):
        return "https://doi.org/" + doi[16:]
    if doi.startswith("10."):
        return "https://doi.org/" + doi
    return None


def title_rows(alluvial):
    rows = []
    for paper in sorted(alluvial["papers"], key=lambda x: (x.get("year") or 0)):
        if not paper.get("year") or not paper.get("title"):
            continue
        rows.append({"year": paper["year"], "topic": paper["topic"], "title": paper["title"],
                     "venue": paper.get("venue") or None, "doi": normalise_doi(paper.get("doi"))})
    return rows


def write_title_vault(titles, password, out_dir):
    """titles: {anon_id: [rows]} → out_dir/titles/{key.json, <id>.json}. Returns file count."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = secrets.token_bytes(16)
    aes = AESGCM(hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS, 32))

    def seal(payload, aad):
        nonce = secrets.token_bytes(12)
        plain = gzip.compress(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(), mtime=0)
        ct = aes.encrypt(nonce, plain, aad.encode())
        return {"nonce": b64(nonce), "ciphertext": b64(ct)}

    folder = os.path.join(out_dir, "titles")
    os.makedirs(folder, exist_ok=True)
    for old in os.listdir(folder):
        if old.endswith(".json"):
            os.remove(os.path.join(folder, old))
    legacy = os.path.join(out_dir, "encrypted_titles.json")
    if os.path.exists(legacy):
        os.remove(legacy)
    for anon, rows in titles.items():
        if not anon.startswith(ID_SHAPE) or "/" in anon:
            raise SystemExit(f"refusing to write a title file for id {anon!r}")
        with open(os.path.join(folder, f"{anon}.json"), "w", encoding="utf-8") as fh:
            json.dump(seal(rows, AAD + anon), fh, separators=(",", ":"))
    key = {"version": 2, "kdf": "PBKDF2-SHA256", "iterations": ITERATIONS, "salt": b64(salt),
           "aad": AAD, "encoding": "gzip", "check": seal("ok", AAD + "check")}
    with open(os.path.join(folder, "key.json"), "w", encoding="utf-8") as fh:
        json.dump(key, fh, separators=(",", ":"))
    return len(titles)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", required=True, help="file with one DIR=ANON_ID per line (private)")
    p.add_argument("--dashboard", default="public/data/dashboard.json")
    p.add_argument("--out-dir", default="public/data/topics")
    p.add_argument("--password-env", default="NAMES_PASSWORD")
    p.add_argument("--env-file", help="private env file holding `export NAMES_PASSWORD=...`")
    a = p.parse_args()
    password = read_password(a.password_env, a.env_file)
    if not password:
        sys.exit(f"{a.password_env} is not set (environment or --env-file); nothing written")
    public = {x["id"] for x in json.load(open(a.dashboard, encoding="utf-8"))["professors"]}
    titles = {}
    for line in open(a.manifest, encoding="utf-8"):
        if not line.strip():
            continue
        folder, anon = line.strip().rsplit("=", 1)
        if anon not in public:
            sys.exit(f"{anon} is not in the public dashboard population — refusing to publish")
        titles[anon] = title_rows(json.load(open(os.path.join(folder, "alluvial.json"), encoding="utf-8")))
    n = write_title_vault(titles, password, a.out_dir)
    papers = sum(len(r) for r in titles.values())
    with_doi = sum(1 for r in titles.values() for x in r if x["doi"])
    print(f"titles/: {n} researcher files, {papers} papers ({with_doi} with DOI), key.json written")


if __name__ == "__main__":
    main()
