import unittest

try:   # the patch tool imports the topic stack (numpy); the deploy runner has none
    from patch_release_verified_works import add_areas, add_lead_works, stage_for_year
except ImportError:
    add_lead_works = None


def professor():
    return {'career': [{'stage': 'doctoral', 'start_year': 2012, 'end_year': 2017},
                       {'stage': 'faculty', 'start_year': 2023, 'end_year': 2026}],
            'phd_year': 2017, 'appointment_year': 2023, 'lead_work_count': 1,
            'yearly': [{'year': 2012, 'stage': 'doctoral', 'total': 0, 'first_author': 0, 'corresponding_author': 0,
                        'impact_low': 0, 'impact_medium': 0, 'impact_high': 0, 'impact_unknown': 0,
                        'mean_journal_2yr_citedness': None, 'article_citations': 0},
                       {'year': 2014, 'stage': 'doctoral', 'total': 1, 'first_author': 1, 'corresponding_author': 0,
                        'impact_low': 0, 'impact_medium': 0, 'impact_high': 0, 'impact_unknown': 0,
                        'mean_journal_2yr_citedness': 7.5, 'article_citations': 40}],
            'journals': [{'journal': 'J A', 'lead_work_count': 1, 'openalex_2yr_mean_citedness': 7.5}]}


@unittest.skipIf(add_lead_works is None, 'numpy not installed')
class PatchReleaseTests(unittest.TestCase):
    def test_new_lead_works_merge_with_published_counts(self):
        p = professor()
        p['yearly'][1]['impact_high'] = 1
        roles = [{'year': 2020, 'author_position': 'first', 'is_corresponding': False, 'cited_by_count': 3,
                  'source': {'display_name': 'J B'}, 'impact': 1.5},
                 {'year': 2014, 'author_position': 'middle', 'is_corresponding': True, 'cited_by_count': 2,
                  'source': {'display_name': 'J A'}, 'impact': 7.5}]
        self.assertEqual(add_lead_works(p, roles, 2026), 2)
        by_year = {y['year']: y for y in p['yearly']}
        self.assertEqual([y['year'] for y in p['yearly']], list(range(2012, 2027)))   # no gaps, doctoral start kept
        self.assertEqual((by_year[2014]['total'], by_year[2014]['corresponding_author'], by_year[2014]['impact_high']), (2, 1, 2))
        self.assertEqual(by_year[2014]['mean_journal_2yr_citedness'], 7.5)
        self.assertEqual((by_year[2020]['total'], by_year[2020]['impact_low'], by_year[2020]['stage']), (1, 1, 'postdoc'))
        self.assertEqual(p['lead_work_count'], 3)
        self.assertEqual(p['journals'], [{'journal': 'J A', 'lead_work_count': 2, 'openalex_2yr_mean_citedness': 7.5},
                                         {'journal': 'J B', 'lead_work_count': 1, 'openalex_2yr_mean_citedness': 1.5}])

    def test_stage_rule_matches_release_builder(self):
        careers = professor()['career']
        self.assertEqual(stage_for_year(careers, 2015, 2017, 2023), 'doctoral')
        self.assertEqual(stage_for_year(careers, 2019, 2017, 2023), 'postdoc')
        self.assertEqual(stage_for_year(careers, 2024, 2017, 2023), 'faculty')

    def test_research_areas_count_new_topics_and_extend_lists(self):
        areas = {'domains': ['Physical Sciences'], 'fields': [['Physics and Astronomy', 0]],
                 'subfields': [['Statistical and Nonlinear Physics', 0]], 'topics': [['Complex Network Analysis', 0]],
                 'researchers': {'P-A': {'n': 1, 'f': [[0, 1]], 's': [[0, 1]], 't': [[0, 1]]}}}
        work = lambda topic: {'primary_topic': {'display_name': topic, 'subfield': {'display_name': 'Statistical and Nonlinear Physics'},
                                                'field': {'display_name': 'Physics and Astronomy'},
                                                'domain': {'display_name': 'Physical Sciences'}}}
        add_areas(areas, 'P-A', [work('Complex Network Analysis'), work('Synchronization'), {'primary_topic': None}])
        self.assertEqual(areas['topics'][1], ['Synchronization', 0])
        self.assertEqual(areas['researchers']['P-A'], {'n': 3, 'f': [[0, 3]], 's': [[0, 3]], 't': [[0, 2], [1, 1]]})


if __name__ == '__main__':
    unittest.main()
