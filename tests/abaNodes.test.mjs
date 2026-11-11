import assert from 'node:assert/strict';
import test from 'node:test';
import nodes from '../work/test-dist/abaNodes.js';

const { indexNodeCitations } = nodes;
const first = { id: 1, year: 2010, title: 'Early   result' };
const middle = { id: 2, year: 2012, title: 'Outside followup' };
const later = { id: 3, year: 2015, title: 'Later result' };
const alternate = { id: 4, year: 2016, title: 'Another result' };
const paths = [{ first, middle, last: later }, { first, middle, last: alternate }];
const titles = [
  { year: 2010, title: 'EARLY result', topic: 7 },
  { year: 2015, title: later.title, topic: 2 },
  { year: 2016, title: alternate.title, topic: 2 },
];
const researcher = {
  eras: [{ start: 2008, end: 2012 }, { start: 2010, end: 2018 }],
  papers: [
    { year: 2010, topic: 7, era: 0 },
    { year: 2010, topic: 2, era: 1 },
    { year: 2015, topic: 2, era: 1 },
    { year: 2016, topic: 2, era: 1 },
  ],
};

test('groups the same middle work only on the exact endpoint nodes', () => {
  const index = indexNodeCitations(paths, titles, researcher, 'year');
  assert.equal(index.get('7:0').size, 1);
  assert.deepEqual(index.get('7:0').get(2).routes.map(x => x.last), ['2:5', '2:6']);
  assert.equal(index.get('2:5').get(2).routes.length, 1);
  assert.equal(index.has('2:0'), false);
  assert.equal(index.has('7:2'), false);
});

test('uses known career columns and declines to guess a mixed cell', () => {
  const placed = indexNodeCitations(paths, titles, researcher, 'era');
  assert.equal(placed.get('7:0').get(2).routes.length, 2);
  const mixed = { ...researcher, papers: [{ year: 2010, topic: 7, era: 1 }, ...researcher.papers] };
  const index = indexNodeCitations(paths, titles, mixed, 'era');
  assert.equal(index.has('7:0'), false);
  assert.equal(index.has('7:1'), false);
  assert.equal(index.get('2:1').get(2).routes[0].first, null);
});

test('does not place a work when its title and year match multiple topics', () => {
  const collision = [...titles, { year: 2010, title: first.title, topic: 2 }];
  const index = indexNodeCitations(paths, collision, researcher, 'year');
  assert.equal(index.has('7:0'), false);
  assert.equal(index.has('2:0'), false);
  assert.equal(index.get('2:5').get(2).routes[0].first, null);
});
