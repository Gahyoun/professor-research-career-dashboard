#!/usr/bin/env python3
"""Export private topic verdicts with the public release's work-level gate.

  python3 backend/topics/koad_verdicts.py --koad-dir "$KOAD_RUN" \
      --source-db "$SOURCE_DATABASE" --professor-uid "$PROFESSOR_UID" \
      --out "$PRIVATE_WORK/verdicts.json"

The default preserves a review record only when the applied source still says
keep and KOAD explicitly says true_paper for the same researcher/work. Optional
drop/skip review policies can narrow that set; keep never overrides this gate.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from release_identity import PublicationIdentityGate


def rows(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def build_verdicts(records, professor_uid, identity, review='source'):
    by_work = {}
    for record in records:
        if record.get('professor_uid') != professor_uid or not record.get('work_id'):
            continue
        work_id = str(record['work_id']).rstrip('/').rsplit('/', 1)[-1]
        previous = by_work.get(work_id)
        if previous and previous.get('decision') != record.get('decision'):
            raise ValueError('Conflicting KOAD records for the same researcher and work')
        by_work[work_id] = record
    verdicts = []
    counts = {'keep': 0, 'drop': 0, 'review': 0}
    for work_id, record in sorted(by_work.items()):
        is_review = record.get('recommended_action') == 'review'
        counts['review'] += int(is_review)
        exclusion = identity.exclusion_reason(professor_uid, work_id)
        allowed = exclusion is None and record.get('decision') == 'true_paper'
        if record.get('recommended_action') == 'drop':
            allowed = False
        if is_review and review == 'skip':
            continue
        if is_review and review == 'drop':
            allowed = False
        counts['keep' if allowed else 'drop'] += 1
        verdicts.append({
            'work_id': f'https://openalex.org/{work_id}', 'is_target': allowed,
            'koad_decision': record.get('decision'), 'koad_confidence': record.get('confidence'),
        })
    return verdicts, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--koad-dir', type=Path, required=True)
    parser.add_argument('--source-db', type=Path, required=True)
    parser.add_argument('--identity-decisions', type=Path)
    parser.add_argument('--professor-uid', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--review', choices=['source', 'drop', 'keep', 'skip'], default='source')
    args = parser.parse_args()
    decisions = args.identity_decisions or args.koad_dir / 'identity_decisions.sqlite'
    if not decisions.exists():
        parser.error('KOAD decision database is required')
    with sqlite3.connect(f'file:{args.source_db.resolve()}?mode=ro&immutable=1', uri=True) as connection:
        connection.execute('ATTACH DATABASE ? AS koad', (f'file:{decisions.resolve()}?mode=ro&immutable=1',))
        identity = PublicationIdentityGate.from_connection(connection)
    records = [record for filename in ('true_papers.jsonl', 'namesake_papers.jsonl', 'review_queue.jsonl')
               for record in rows(args.koad_dir / filename)]
    verdicts, counts = build_verdicts(records, args.professor_uid, identity, args.review)
    args.out.write_text(json.dumps(verdicts, ensure_ascii=False), encoding='utf-8')
    print(f"keep {counts['keep']} · drop {counts['drop']} · review {counts['review']} (policy {args.review})")


if __name__ == "__main__":
    main()
