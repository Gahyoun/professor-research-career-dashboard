"""Keep recorded faculty semesters independent of publication identity verdicts."""
from collections import defaultdict
import re


def period(index):
    return f'{index // 2}-H{index % 2 + 1}'


def index(value):
    match = re.fullmatch(r'(\d{4})-H([12])', value or '')
    return int(match[1]) * 2 + int(match[2]) - 1 if match else None


def unique_evidence_unit(rows):
    """Resolve only unanimous actual units; a shared display name is not proof."""
    units = {row.get('institution_unit_id') for row in rows}
    return next(iter(units)) if len(units) == 1 and None not in units else None


def reconcile_observed_faculty(careers, observations, release_year):
    """Preserve verified jobs; replace conflicting inferred rows by observations.

    Roster gaps do not establish continuous employment. Simultaneous observed
    institutions do not establish an exclusive move. Campus units stay separate.
    """
    by_period = defaultdict(set)
    by_unit = defaultdict(set)
    for row in observations:
        year = row.get('year')
        term = row.get('term') or ''
        match = re.fullmatch(r'(\d{4})-(spring|fall)', term)
        if (not match or type(year) is not int or int(match[1]) != year
                or not 1900 <= year <= int(release_year)
                or row.get('semester') not in (None, match[2])
                or not row.get('institution_unit_id') or not row.get('institution')):
            continue
        key = (row['institution_unit_id'], row['institution'])
        value = year * 2 + int(match[2] == 'fall')
        by_period[value].add(key)
        by_unit[key].add(value)
    if not by_unit:
        return [{k: v for k, v in c.items() if not k.startswith('_')} for c in careers]
    ambiguous_roster = any(len(units) > 1 for units in by_period.values())

    kept = []
    for original in careers:
        item = dict(original)
        if (item['stage'] == 'postdoc' and item.get('_publication_inferred_postdoc')
                and not item.get('_explicit_verified') and not ambiguous_roster):
            unit = item.get('_institution_unit_id')
            start, end = index(item.get('start_period')), index(item.get('end_period'))
            if unit and start is not None and end is not None:
                excluded = {when for when, units in by_period.items() if any(key[0] == unit for key in units)}
                remaining = [when for when in range(start, end + 1) if when not in excluded]
                groups = []
                for when in remaining:
                    if not groups or when > groups[-1][-1] + 1:
                        groups.append([])
                    groups[-1].append(when)
                for group in groups:
                    part = dict(item)
                    part.update(start_period=period(group[0]), end_period=period(group[-1]),
                                start_year=group[0] // 2, end_year=group[-1] // 2)
                    if len(remaining) != end - start + 1:
                        part['evidence_basis'] = (part.get('evidence_basis') or '') + '; 실제 명부의 동일기관 교수 관측 학기는 추정 포닥에서 제외'
                    kept.append(part)
                continue
        if item['stage'] == 'faculty' and not item.get('_explicit_verified') and not ambiguous_roster:
            start, end = index(item.get('start_period')), index(item.get('end_period'))
            if start is not None and end is not None:
                def same(key):
                    unit = item.get('_institution_unit_id')
                    return unit == key[0] if unit else item['institution'] == key[1]
                conflicting = any(start <= when <= end and len(units) == 1
                                  and not same(next(iter(units))) for when, units in by_period.items())
                if conflicting:
                    continue
        kept.append(item)

    for (unit, name), values in sorted(by_unit.items()):
        groups = []
        for value in sorted(values):
            if not groups or value > groups[-1][-1] + 1:
                groups.append([])
            groups[-1].append(value)
        for values in groups:
            kept.append({'stage': 'faculty', 'position_no': None, 'institution': name,
                'start_period': period(values[0]), 'end_period': period(values[-1]),
                'start_year': values[0] // 2, 'end_year': values[-1] // 2,
                'confidence': 'medium' if ambiguous_roster else 'confirmed',
                'is_institution_successor': False, 'is_estimated': False,
                'evidence_basis': ('교수 명부의 복수기관 관측; 겸직·배타적 이동 여부 미확인' if ambiguous_roster else
                                   '교수 명부에 실제 기록된 학기 관측; 논문 소속과 독립된 재직 근거'),
                '_institution_unit_id': unit})

    # Merge only overlapping or adjacent spells of the same resolved unit.
    # Never bridge an unobserved semester or join two campuses by parent name.
    result = []
    for item in sorted(kept, key=lambda c: (c.get('start_period') or '', c['stage'], c['institution'])):
        candidates = [c for c in result if c['stage'] == item['stage'] == 'faculty'
                      and c['institution'] == item['institution']
                      and c.get('_institution_unit_id') == item.get('_institution_unit_id')]
        previous = candidates[-1] if candidates else None
        left, right = index(previous.get('end_period')) if previous else None, index(item.get('start_period'))
        if previous and left is not None and right is not None and right <= left + 1:
            if index(item.get('end_period')) is not None and index(item['end_period']) > left:
                previous['end_period'], previous['end_year'] = item['end_period'], item['end_year']
            previous['evidence_basis'] = '; '.join(dict.fromkeys(filter(None, [previous.get('evidence_basis'), item.get('evidence_basis')])))
        else:
            result.append(dict(item))
    return [{k: v for k, v in c.items() if not k.startswith('_')} for c in result]
