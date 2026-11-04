import unittest

from observed_careers import reconcile_observed_faculty, unique_evidence_unit


def observation(term, institution, unit=None):
    return {'term': term, 'year': int(term[:4]), 'semester': term.split('-')[1],
            'institution': institution, 'institution_unit_id': unit or institution}


def career(institution, start, end, verified=False):
    return {'stage': 'faculty', 'position_no': 1, 'institution': institution,
            'start_period': start, 'end_period': end, 'start_year': int(start[:4]), 'end_year': int(end[:4]),
            'confidence': 'confirmed', 'is_estimated': False, 'is_institution_successor': False,
            'evidence_basis': 'Synthetic existing history', '_institution_unit_id': institution,
            '_explicit_verified': verified}


class ObservedCareerTests(unittest.TestCase):
    def test_observed_move_overrides_conflicting_inferred_current_interval(self):
        existing = [career('University B', '2010-H1', '2026-H1')]
        records = [observation(f'{y}-{s}', 'University A (Branch Campus)') for y in (2023, 2024) for s in ('spring', 'fall')]
        records += [observation(term, 'University B') for term in ('2025-spring', '2025-fall', '2026-spring')]
        out = reconcile_observed_faculty(existing, records, 2026)
        self.assertEqual([(c['institution'], c['start_period'], c['end_period']) for c in out], [
            ('University A (Branch Campus)', '2023-H1', '2024-H2'), ('University B', '2025-H1', '2026-H1')])
        self.assertTrue(all(not c['is_estimated'] for c in out))
        self.assertTrue(all('department' not in c for c in out))
        self.assertTrue(all(not k.startswith('_') for c in out for k in c))
        self.assertEqual(existing[0]['start_period'], '2010-H1')

    def test_first_observation_can_extend_late_current_interval(self):
        out = reconcile_observed_faculty([career('University B', '2025-H2', '2026-H1')],
            [observation(t, 'University B') for t in ('2025-spring', '2025-fall', '2026-spring')], 2026)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]['start_period'], out[0]['end_period']), ('2025-H1', '2026-H1'))

    def test_explicit_verified_history_is_not_overwritten(self):
        out = reconcile_observed_faculty([career('University B', '2010-H1', '2026-H1', verified=True)],
            [observation('2023-spring', 'University A'), observation('2025-spring', 'University B')], 2026)
        old = next(c for c in out if c['institution'] == 'University B')
        self.assertEqual((old['start_period'], old['end_period']), ('2010-H1', '2026-H1'))

    def test_dual_observations_do_not_establish_an_exclusive_move(self):
        records = [observation('2023-spring', 'University A'), observation('2023-spring', 'University B')]
        out = reconcile_observed_faculty([career('University C', '2020-H1', '2026-H1')], records, 2026)
        self.assertEqual({c['institution'] for c in out}, {'University A', 'University B', 'University C'})
        self.assertEqual(next(c for c in out if c['institution'] == 'University C')['start_period'], '2020-H1')
        self.assertTrue(all(c['confidence'] == 'medium' for c in out if c['institution'] != 'University C'))

    def test_missing_semester_and_campus_units_are_not_joined(self):
        records = [observation('2023-spring', 'University A (North Campus)', 'unit-north'),
                   observation('2024-spring', 'University A (North Campus)', 'unit-north'),
                   observation('2023-spring', 'University A (South Campus)', 'unit-south')]
        out = reconcile_observed_faculty([], records, 2026)
        self.assertEqual(len(out), 3)
        self.assertTrue(all(c['start_period'] == c['end_period'] for c in out))

    def test_invalid_terms_and_unresolved_units_are_not_observations(self):
        records = [observation('2023-spring', 'University A'), observation('2027-spring', 'University A')]
        records[0]['year'] = 2024
        records.append({**observation('2024-spring', 'University A'), 'institution_unit_id': None})
        self.assertEqual(reconcile_observed_faculty([], records, 2026), [])

    def test_actual_affiliation_unit_prevents_duplicate_observed_career(self):
        rows = [{'institution_unit_id': 'campus-one'}, {'institution_unit_id': 'campus-one'}]
        inferred = career('University A', '2014-H2', '2026-H2')
        inferred['_institution_unit_id'] = unique_evidence_unit(rows)
        out = reconcile_observed_faculty([inferred], [observation('2024-spring', 'University A', 'campus-one')], 2026)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]['start_period'], out[0]['end_period']), ('2014-H2', '2026-H2'))
        self.assertIsNone(unique_evidence_unit(rows + [{'institution_unit_id': 'campus-two'}]))
        self.assertIsNone(unique_evidence_unit([{'institution_unit_id': None}]))

    def test_only_observed_same_unit_semesters_are_removed_from_inferred_postdoc(self):
        inferred = {**career('University A', '2021-H1', '2026-H1'), 'stage': 'postdoc',
                    '_publication_inferred_postdoc': True}
        records = [observation('2024-spring', 'University A'), observation('2024-fall', 'University A'),
                   observation('2025-spring', 'University A'), observation('2026-spring', 'University A')]
        out = reconcile_observed_faculty([inferred], records, 2026)
        self.assertEqual([(c['start_period'], c['end_period']) for c in out if c['stage'] == 'postdoc'],
                         [('2021-H1', '2023-H2'), ('2025-H2', '2025-H2')])
        self.assertEqual(inferred['end_period'], '2026-H1')

    def test_explicit_postdoc_and_other_campus_are_preserved(self):
        inferred = {**career('University A', '2024-H1', '2024-H2'), 'stage': 'postdoc',
                    '_publication_inferred_postdoc': True}
        records = [observation('2024-spring', 'University A', 'another-campus')]
        self.assertTrue(any(c['stage'] == 'postdoc' for c in reconcile_observed_faculty([inferred], records, 2026)))
        inferred['_explicit_verified'] = True
        records = [observation('2024-spring', 'University A')]
        self.assertEqual(next(c for c in reconcile_observed_faculty([inferred], records, 2026) if c['stage'] == 'postdoc')['start_period'], '2024-H1')
        inferred['_explicit_verified'] = False
        inferred['_publication_inferred_postdoc'] = False
        self.assertTrue(any(c['stage'] == 'postdoc' for c in reconcile_observed_faculty([inferred], records, 2026)))


if __name__ == '__main__':
    unittest.main()
