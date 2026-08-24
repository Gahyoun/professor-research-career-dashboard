#!/usr/bin/env python3
import argparse
import json
import sqlite3
import shutil
from pathlib import Path

parser = argparse.ArgumentParser(description='Prepare a yearly dashboard release from the private career DB.')
parser.add_argument('--year', required=True)
parser.add_argument('--db', required=True)
parser.add_argument('--project-root', default=str(Path(__file__).resolve().parents[2]))
parser.add_argument('--author-aliases', help='Optional private JSON exported from profile workbooks')
args = parser.parse_args()

root = Path(args.project_root)
cache = root / 'backend' / 'cache' / args.year
cache.mkdir(parents=True, exist_ok=True)

uri = f"file:{Path(args.db).resolve()}?mode=ro&immutable=1"
con = sqlite3.connect(uri, uri=True)
ids = [row[0] for row in con.execute(
    "SELECT DISTINCT openalex_id FROM professors WHERE openalex_id IS NOT NULL ORDER BY openalex_id"
)]
con.close()
(cache / 'author_ids.json').write_text(json.dumps(ids))
(cache / 'source_db_path.txt').write_text(str(Path(args.db).resolve()))
if args.author_aliases:
    shutil.copy2(Path(args.author_aliases).resolve(), cache / 'author_aliases.json')
print(json.dumps({'release_year': args.year, 'author_ids': len(ids), 'author_aliases': (cache / 'author_aliases.json').exists(), 'cache': str(cache)}))
