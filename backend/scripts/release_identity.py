"""Work-level publication gate shared by the public release builders.

An author alias identifies a candidate person, not every paper in that profile.
This gate does not change KOAD classifications or the private source database.
"""
from dataclasses import dataclass
import sqlite3
from pathlib import Path


IDENTITY_FILTER_VERSION = 'KOAD 1.2-positive-work-decision'


def decision_database_path(source_db, cache=None, explicit=None):
    if explicit:
        return Path(explicit)
    if cache:
        source_pointer = Path(cache) / 'source_db_path.txt'
        decision_pointer = Path(cache) / 'identity_decisions_path.txt'
        if source_pointer.exists() and decision_pointer.exists():
            prepared_source = Path(source_pointer.read_text().strip()).resolve()
            if prepared_source == Path(source_db).resolve():
                return Path(decision_pointer.read_text().strip())
    return Path(source_db).resolve().parent / 'identity_decisions.sqlite'

# Both joins are person/work specific. A decision for a namesake or a quarantined
# source row must never authorize another person's publication or affiliation.
STRICT_IDENTITY_PREDICATE = """
EXISTS (
  SELECT 1 FROM work_authorship_evidence identity_source
  JOIN koad.work_decision identity_koad USING(professor_uid,work_id)
  WHERE identity_source.professor_uid={alias}.professor_uid
    AND identity_source.work_id={alias}.work_id
    AND identity_source.identity_decision='keep'
    AND identity_koad.decision='true_paper'
)
"""


@dataclass
class PublicationIdentityGate:
    decisions: dict[tuple[str, str], str]
    kept_source_pairs: set[tuple[str, str]]

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection):
        decisions = {
            (row[0], row[1]): row[2]
            for row in connection.execute(
                'SELECT professor_uid,work_id,decision FROM koad.work_decision'
            )
        }
        kept_source_pairs = {
            (row[0], row[1])
            for row in connection.execute(
                "SELECT professor_uid,work_id FROM work_authorship_evidence "
                "WHERE identity_decision='keep'"
            )
        }
        return cls(decisions, kept_source_pairs)

    def exclusion_reason(self, professor_uid, work_id):
        pair = (professor_uid, work_id)
        decision = self.decisions.get(pair)
        if decision is None:
            return 'missing_koad_decision'
        if decision != 'true_paper':
            return 'namesake_paper' if decision == 'namesake_paper' else 'unresolved_koad_decision'
        if pair not in self.kept_source_pairs:
            return 'missing_kept_source_evidence'
        return None

    @property
    def unclassified_kept_source_count(self):
        return len(self.kept_source_pairs.difference(self.decisions))


def register_author_alias(mapping, primary_owners, author_id, professor_uid):
    """Register a candidate without merging people or approving profile works.

    Mixed OpenAlex profiles and duplicate roster entries can share an ID. Every
    candidate still needs its own positive professor/work decision at publication.
    """
    mapping.setdefault(author_id, set()).add(professor_uid)


def alias_professor_uid(record, known_uids, source_to_uid):
    """Explicit UIDs support roster entries whose source identifier is null."""
    uid = record.get('professor_uid')
    if uid is not None:
        if uid not in known_uids:
            raise ValueError('Alias mapping refers to an unknown researcher')
        return uid
    import re
    source_id = re.sub(r'[^a-z0-9]', '', str(record.get('source_professor_id') or '').lower())
    return source_to_uid.get(source_id) if source_id else None
