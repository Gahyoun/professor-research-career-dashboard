import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'topics'


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    semantics = load('topic_semantics')   # needs numpy + scikit-learn
except ImportError:
    semantics = None
build = load('build_release_topics')


@unittest.skipIf(semantics is None, 'numpy / scikit-learn not installed')
class TopicTermFilter(unittest.TestCase):
    def test_names_and_page_boilerplate_are_never_terms(self):
        for term in ['yong choi', 'seungnam cha', 'kwangyeol lee', 'choi seong-chul', 'man-kee baek', 'kim kim', 'jeong-heui lee', 'orcid org', 'chung-ang university', 'koreamore']:
            self.assertTrue(semantics.boiler(term), term)
        for term in ['phase transition', 'main chain', 'graphene oxide', 'korean peninsula', 'sun light', 'national park', 'song bird']:
            self.assertFalse(semantics.boiler(term), term)

    def test_exclude_list_removes_terms(self):
        docs = {0: ['alpha beta gamma delta'] * 3, 1: ['epsilon zeta eta theta'] * 3}
        terms = semantics.ctfidf_terms(docs, n_terms=6, exclude=frozenset({'alpha beta', 'alpha'}))
        self.assertFalse(any('alpha' == t or 'alpha beta' == t for t in terms[0]))
        self.assertTrue(semantics.excluded('ji-ung jeung', frozenset({'ji ung'})))
        self.assertFalse(semantics.excluded('phase transition', frozenset({'ji ung'})))
        self.assertFalse(semantics.excluded('c-h activation', frozenset({'c h', 'h activation'})))


class AbstractCleaning(unittest.TestCase):
    def test_scraped_pages_and_cover_blurbs_are_dropped(self):
        for text in ['Search for more papers by this author ORCID', 'In article number 2100123, A. Kim and co-workers ...',
                     'Correction for "X" by S. Ringe et al.', 'Department of Physics, Example University, Seoul']:
            self.assertEqual(build.clean_abstract(text), '', text)

    def test_markup_is_stripped(self):
        self.assertEqual(build.clean_abstract('A <mml:math><mml:mi>x</mml:mi></mml:math> film of $\\mathrm{TiO}_2$ and \\ensuremath{\\alpha} phase'),
                         'A x film of and phase')

    def test_copyright_tail_is_cut(self):
        self.assertEqual(build.clean_abstract('We study X. © 2020 Elsevier Ltd. All rights reserved.'), 'We study X.')

    def test_era_index_uses_latest_containing_segment(self):
        eras = [{'start': 2000, 'end': 2005}, {'start': 2005, 'end': 2010}, {'start': 2012, 'end': None}]
        self.assertEqual([build.era_index(eras, y) for y in (1998, 2005, 2011, 2020)], [0, 1, 1, 2])



@unittest.skipIf(semantics is None, 'numpy / scikit-learn not installed')
class CompactIndex(unittest.TestCase):
    def test_columns_and_derivable_tags(self):
        import sys
        sys.path.insert(0, str(ROOT))
        compact = load('compact_index')
        t1 = {"id": 0, "label": "Spin glass · Other", "keywords": ["Replica", "spin glass"]}
        t1["tags"] = semantics.english_tags(t1["label"], t1["keywords"])
        t2 = {"id": 1, "label": "x", "keywords": [], "tags": {"en": ["hand made"], "ko": []}}
        r = compact.compact_researcher({"topics": [t1, t2], "papers": [
            {"year": 2010, "topic": 0, "era": 1, "cited": 3}, {"year": 2004, "topic": 1, "era": None}]})
        self.assertNotIn("papers", r)
        self.assertEqual(r["paper_cols"], {"year": [2004, 2010], "topic": [1, 0], "era": [None, 1], "cited": [0, 3]})
        self.assertNotIn("tags", r["topics"][0])
        self.assertEqual(r["topics"][1]["tags"]["en"], ["hand made"])


if __name__ == '__main__':
    unittest.main()
