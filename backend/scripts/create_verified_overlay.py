#!/usr/bin/env python3
"""Create a PRIVATE SQLite review overlay from explicitly reviewed JSON rows."""
import argparse
import json
from pathlib import Path
import sqlite3


def create_overlay(records_path, output):
    if output.exists():
        raise ValueError('Output already exists; choose a new private overlay instead of overwriting audit history.')
    records = json.loads(records_path.read_text())
    output.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(output)
    try:
        connection.executescript((Path(__file__).parent / 'verified_departments_schema.sql').read_text())
        columns = [row[1] for row in connection.execute('PRAGMA table_info(degree_department_verifications)') if row[1] != 'verification_id']
        query = 'INSERT INTO degree_department_verifications (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')'
        for record in records:
            if set(record) != set(columns):
                raise ValueError('Overlay record schema mismatch.')
            if len((record['evidence_excerpt'] or '').split()) > 25:
                raise ValueError('A source excerpt exceeds the 25-word limit.')
            result = connection.execute(query, [record[column] for column in columns])
            if record['evidence_type'] == 'search_only':
                connection.execute('''INSERT INTO verification_search_audit
                    (verification_id,provider,search_url,result_status,checked_at,notes)
                    VALUES (?,?,?,?,?,?)''', (result.lastrowid, 'RISS', record['source_url'], record['verification_status'], record['checked_at'], 'Indexed author+institution+year searches and direct author-page request; bounded pilot, not an exhaustive catalog audit.'))
                connection.execute('''INSERT INTO verification_search_audit
                    (verification_id,provider,search_url,result_status,checked_at,notes)
                    VALUES (?,?,?,?,?,?)''', (result.lastrowid, 'KISS', 'https://kiss.kstudy.com/', 'robots_limited_no_degree_record', record['checked_at'], 'Official-domain indexed search attempted; returned namesake/journal records do not establish a doctorate department.'))
        connection.commit()
    except Exception:
        connection.close()
        output.unlink(missing_ok=True)
        raise
    connection.close()
    output.chmod(0o600)
    print(json.dumps({'records': len(records), 'verified': sum(row['verification_status'] == 'verified' for row in records)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records-json', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    create_overlay(args.records_json, args.output)
