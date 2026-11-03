import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'topics'
spec = importlib.util.spec_from_file_location('info_flow', ROOT / 'info_flow.py')
info_flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(info_flow)


def corpus(spec):
    """[(year, topic, refs)] → parallel lists."""
    return [s[0] for s in spec], [s[1] for s in spec], [s[2] for s in spec]


class EntropyTests(unittest.TestCase):
    def test_plugin_entropy_and_correction(self):
        self.assertAlmostEqual(info_flow.entropy([1, 1, 1, 1], corrected=False), 2.0)
        self.assertGreater(info_flow.entropy([1, 1, 1, 1]), 2.0)
        self.assertEqual(info_flow.entropy([]), 0.0)
        self.assertEqual(info_flow.entropy([5]), 0.0)

    def test_jsd_bounds(self):
        self.assertAlmostEqual(info_flow.jsd({0: 3, 1: 1}, {0: 6, 1: 2}), 0.0)
        self.assertAlmostEqual(info_flow.jsd({0: 4}, {1: 4}), 1.0)
        self.assertIsNone(info_flow.jsd({}, {0: 1}))


class TransitionTests(unittest.TestCase):
    def test_continuation_has_no_divergence_or_merge(self):
        years, topics, refs = corpus(
            [(2001, 0, ['a1', 'a2']), (2001, 0, ['a1', 'a3']), (2001, 1, ['b1', 'b2']), (2001, 1, ['b1', 'b3']),
             (2004, 0, ['a1', 'a4']), (2004, 0, ['a2', 'a5']), (2004, 1, ['b1', 'b4']), (2004, 1, ['b2', 'b5'])])
        out = info_flow.analyse(years, topics, refs, width=3, n_null=20, n_boot=20, seed=1)
        row = out['transitions'][0]
        self.assertEqual((row['from'], row['to']), ([2001, 2003], [2004, 2004]))
        self.assertAlmostEqual(row['diverge'], 0.0, places=6)
        self.assertAlmostEqual(row['merge'], 0.0, places=6)
        self.assertGreater(row['continuity'], 0.99)
        self.assertEqual(row['birth_share'], 0.0)

    def test_split_is_divergence_and_merge_is_merge(self):
        split = corpus([(2001, 0, ['a1', 'a2']), (2001, 0, ['a1', 'a3']),
                        (2004, 1, ['a1', 'x1']), (2004, 1, ['a2', 'x2']), (2004, 2, ['a1', 'y1']), (2004, 2, ['a3', 'y2'])])
        row = info_flow.analyse(*split, n_null=10, n_boot=10)['transitions'][0]
        self.assertGreater(row['diverge'], 0.9)
        self.assertAlmostEqual(row['merge'], 0.0, places=6)

        merge = corpus([(2001, 1, ['a1', 'a2']), (2001, 1, ['a1', 'a3']), (2001, 2, ['b1', 'b2']), (2001, 2, ['b1', 'b3']),
                        (2004, 3, ['a1', 'b1']), (2004, 3, ['a2', 'b2']), (2004, 3, ['a3', 'b3'])])
        row = info_flow.analyse(*merge, n_null=10, n_boot=10)['transitions'][0]
        self.assertGreater(row['merge'], 0.9)
        self.assertAlmostEqual(row['diverge'], 0.0, places=6)

    def test_births_and_endings_use_the_empty_state(self):
        years, topics, refs = corpus([(2001, 0, ['a1', 'a2']), (2001, 1, ['z1']),
                                      (2004, 0, ['a1', 'a9']), (2004, 2, ['n1', 'n2'])])
        row = info_flow.analyse(years, topics, refs, n_null=5, n_boot=5)['transitions'][0]
        flows = {(a, b): m for a, b, m in row['flows']}
        self.assertEqual(flows[(None, 2)], 1.0)   # topic 2 shares no reference with 2001–03
        self.assertEqual(flows[(1, None)], 1.0)   # topic 1 has no successor in 2004
        self.assertEqual(row['birth_share'], 0.5)
        self.assertEqual(row['ending_share'], 0.5)

    def test_gap_windows_are_kept_but_not_paired(self):
        years, topics, refs = corpus([(2001, 0, ['a']), (2010, 0, ['a'])])
        out = info_flow.analyse(years, topics, refs, n_null=5, n_boot=5)
        self.assertEqual(out['transitions'], [])
        self.assertEqual([w['n'] for w in out['windows']], [1, 0, 0, 1])

    def test_deterministic_with_seed_and_null_reported(self):
        years, topics, refs = corpus([(2000 + i % 9, i % 3, [f'r{i % 3}{j}' for j in range(i % 4 + 1)] + [f'u{i}']) for i in range(40)])
        a = info_flow.analyse(years, topics, refs, n_null=30, n_boot=30, seed=7)
        b = info_flow.analyse(years, topics, refs, n_null=30, n_boot=30, seed=7)
        self.assertEqual(a, b)
        row = a['transitions'][0]
        self.assertEqual(len(row['continuity_null']), 2)
        lo, hi = row['continuity_ci']
        self.assertLessEqual(lo, hi)
        self.assertEqual(a['summary']['transitions'], len(a['transitions']))


if __name__ == '__main__':
    unittest.main()
