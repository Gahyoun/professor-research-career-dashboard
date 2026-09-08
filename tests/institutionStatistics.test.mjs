import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { buildInstitutionStatistics, empiricalQuantile } from '../work/test-dist/institutionStatistics.js';
import { mergeMetadata } from '../work/test-dist/metadata.js';

const appointment = (institution, year, extra = {}) => ({ institution, country: 'KR', role: 'faculty',
  start_year: year, end_year: year, evidence_kind: 'semester_roster', evidence_status: 'observed',
  observed_terms: [`${year}-spring`], department: null, ...extra });
const person = (id, appointments, extra = {}) => ({ id, subject: 'physics', faculty_appointments: appointments,
  phd_institution: null, phd_country: null, phd_year: null, career: [], ...extra });
const build = (people, options = {}) => buildInstitutionStatistics(people, { releaseYear: 2026, ...options });
const point = (data, label, year) => data.institutions.find(i => i.label === label).years.find(y => y.year === year);

test('same-semester roster counts exclude inferred careers, official overlays and missing terms without department/country gating', () => {
  const rows = [person('a', [appointment('A', 2024, {country:null}), appointment('A', 2025)], { career:[{institution:'False career',stage:'faculty',start_year:2000,end_year:2026}] }),
    person('b', [appointment('A',2024,{observed_terms:['2024-fall']}), appointment('A',2025,{observed_terms:undefined})]),
    person('c', [appointment('A',2024,{evidence_kind:'verified_cv',evidence_status:'verified'})]),
    person('d', [appointment('A',2026,{observed_terms:['2025-spring']})])];
  const data=build(rows); assert.deepEqual(data.years,[2024,2025]); assert.equal(point(data,'A',2024).count,1);
  assert.equal(data.coverage.observedPeople,1);assert.equal(data.coverage.missingTermRows,2);assert.equal(data.coverage.ignoredAppointmentRows,1);
  assert.equal(build(rows,{term:'fall'}).coverage.observedPeople,1);assert.equal(data.institutions.length,1);
});

test('unique researchers and unit observations are deduplicated, while multiaffiliation does not inflate the national denominator', () => {
  const a=person('PRIVATE-ID',[appointment('A',2024),appointment('A',2024),appointment('B',2024)],{name:'PRIVATE NAME',source_url:'https://private.example/secret'});
  const before=JSON.stringify(a);const data=build([a,a]);assert.equal(data.coverage.duplicateIds,1);
  assert.equal(data.coverage.annual[0].people,1);assert.equal(point(data,'A',2024).count,1);assert.equal(point(data,'B',2024).count,1);
  assert.equal(JSON.stringify(a),before);assert.ok(!/PRIVATE|private\.example/.test(JSON.stringify(data)));
});

test('different subject frames suppress pooled changes; an explicit shared subject permits the observed comparison', () => {
  const rows=[person('p',[appointment('A',2023),appointment('A',2024)]),person('m',[appointment('A',2024)],{subject:'mathematics'})];
  const pooled=point(build(rows),'A',2024);assert.equal(pooled.change,null);assert.equal(pooled.movement.movesIn,null);
  assert.match(pooled.movement.reason,/수집 분야/);const physics=point(build(rows,{subject:'physics'}),'A',2024);
  assert.equal(physics.count,1);assert.equal(physics.change,0);assert.equal(physics.movement.retained,1);
});

test('missing entire years and absent fall 2026 do not manufacture movement or zero-person snapshots', () => {
  const data=build([person('a',[appointment('A',2023),appointment('B',2025)])]);
  assert.deepEqual(data.years,[2023,2025]);assert.equal(point(data,'B',2025).movement.comparable,false);
  assert.equal(point(data,'B',2025).movement.previousYear,null);
  const fall=build([person('a',[appointment('A',2025,{observed_terms:['2025-fall']})])],{term:'fall'});
  assert.deepEqual(fall.years,[2025]);assert.equal(fall.institutions[0].years.length,1);assert.equal(fall.institutions[0].years[0].movement.movesOut,null);
});

test('entry and exit decompositions preserve observed totals and distinguish changes, observation loss, and ambiguous institutions', () => {
  const rows=[person('keep',[appointment('A',2024),appointment('A',2025)]),
    person('in',[appointment('B',2024),appointment('A',2025)]),person('out',[appointment('A',2024),appointment('B',2025)]),
    person('first',[appointment('A',2025)]),person('lost',[appointment('A',2024)]),
    person('ambIn',[appointment('B',2024),appointment('C',2024),appointment('A',2025)]),
    person('ambOut',[appointment('A',2024),appointment('C',2024),appointment('B',2025)])];
  const p=point(build(rows),'A',2025),m=p.movement;
  assert.equal(p.count,4);assert.equal(m.previousCount,4);assert.equal(m.retained,1);assert.equal(m.added,3);assert.equal(m.removed,3);
  assert.equal(m.movesIn,1);assert.equal(m.movesOut,1);assert.equal(m.priorUnobserved,1);assert.equal(m.nextUnobserved,1);
  assert.equal(m.ambiguousIn,1);assert.equal(m.ambiguousOut,1);assert.equal(p.change,0);
  assert.equal(m.added,m.movesIn+m.mergerIn+m.priorUnobserved+m.ambiguousIn);
  assert.equal(m.removed,m.movesOut+m.mergerOut+m.nextUnobserved+m.ambiguousOut);
  assert.deepEqual(m.sources,[{label:'B',count:1,share:1}]);assert.deepEqual(m.destinations,[{label:'B',count:1,share:1}]);
});

test('unresolved schools remain in observed coverage and suspend movement rather than becoming a shared unknown institution', () => {
  const data=build([person('a',[appointment('A',2024),appointment('9999',2025)]),person('b',[appointment('9999',2024),appointment('A',2025)])]);
  assert.equal(data.coverage.annual[0].people,2);assert.equal(data.coverage.annual[0].unresolvedInstitutionPeople,1);
  assert.equal(data.institutions.length,1);const m=point(data,'A',2025).movement;
  assert.equal(m.ambiguousIn,1);assert.equal(m.ambiguousOut,1);assert.equal(m.movesIn,0);assert.equal(m.movesOut,0);
  assert.equal(m.priorUnobserved,0);assert.equal(m.nextUnobserved,0);assert.equal(point(data,'A',2025).shareOfObserved,.5);
});

test('dated mergers group current successors, preserve historical school labels and exclude succession from job changes', () => {
  const rows=[person('gnu',[appointment('경남과학기술대학교',2020),appointment('Gyeongsang National University',2021)]),
    person('kw',[appointment('Kangwon National University',2025),appointment('Kangwon National University',2026)]),
    person('gw',[appointment('Gangneung-Wonju National University',2025),appointment('Gangneung-Wonju National University',2026)])];
  const before=JSON.stringify(rows),data=build(rows),gnu=point(data,'경상국립대학교',2021),kw=point(data,'강원대학교 (통합)',2026);
  assert.equal(gnu.movement.mergerIn,1);assert.equal(gnu.movement.movesIn,0);assert.equal(kw.count,2);assert.equal(kw.movement.mergerIn,1);assert.equal(kw.movement.retained,1);
  assert.equal(kw.movement.movesIn,0);assert.equal(point(data,'Gangneung-Wonju National University',2025).count,1);
  assert.equal(JSON.stringify(rows),before);
  const early=build([person('early',[appointment('강릉원주대학교',2024),appointment('강원대학교',2025)])]);
  assert.equal(point(early,'강원대학교 (통합)',2025).movement.movesIn,1);assert.equal(point(early,'강원대학교 (통합)',2025).movement.mergerIn,0);
  const aliases=build([person('same',[appointment('강릉원주대학교',2024),appointment('Gangneung–Wonju National University',2025)]),
    person('anchor',[appointment('강원대',2024),appointment('Kangwon National University',2025)])]);
  assert.equal(point(aliases,'Gangneung-Wonju National University',2025).movement.retained,1);
  assert.equal(point(aliases,'강원대학교 (통합)',2025).movement.retained,1);
});

test('origin percentages use all observed people including unknowns, keep degree history, and bound missing-country uncertainty', () => {
  const rows=[person('kr',[appointment('A',2025)],{phd_institution:'경남과학기술대학교',phd_country:'KR',phd_year:1990}),
    person('us',[appointment('A',2025)],{phd_institution:'MIT',phd_country:'US',phd_year:2000}),
    person('missing',[appointment('A',2025)],{phd_institution:'1234',phd_country:null,phd_year:2030})];
  const o=point(build(rows),'A',2025).origins;assert.equal(o.total,3);assert.equal(o.domestic,1);assert.equal(o.foreign,1);assert.equal(o.unknownCountry,1);
  assert.equal(o.unknownSchool,1);assert.equal(o.schools.find(s=>s.label==='경남과학기술대학교').count,1);
  assert.equal(o.schools.find(s=>s.label==='Massachusetts Institute of Technology').share,1/3);
  assert.equal(o.countries.reduce((sum,c)=>sum+c.count,0),3);assert.deepEqual(o.foreignShareBounds,{lower:1/3,upper:2/3});
  assert.equal(o.validPhdYears,2);assert.equal(o.missingOrInvalidPhdYears,1);assert.equal(o.medianPhdYear,1995);
  assert.equal(o.q1PhdYear,1992.5);assert.equal(o.q3PhdYear,1997.5);assert.equal(empiricalQuantile([], .5),null);
});

test('actual release uses 2024–2026 spring snapshots and retains the physics-only 2023 coverage warning', () => {
  const dashboard=JSON.parse(readFileSync('public/data/dashboard.json','utf8'));
  const metadata=JSON.parse(readFileSync('public/data/constellation_metadata.json','utf8'));
  const people=mergeMetadata(dashboard,metadata).professors;
  const spring=build(people);assert.deepEqual(spring.coverage.annual.map(y=>[y.year,y.people]),[[2023,699],[2024,3354],[2025,3213],[2026,3241]]);
  assert.deepEqual(spring.coverage.annual[0].subjects.map(s=>s.label),['physics']);
  assert.ok(spring.institutions.every(i=>i.years.find(y=>y.year===2024).movement.comparable===false));
  const movementTotal=(year,field)=>spring.institutions.reduce((sum,i)=>sum+i.years.find(y=>y.year===year).movement[field],0);
  assert.equal(movementTotal(2025,'movesIn'),50);assert.equal(movementTotal(2026,'movesIn'),19);
  assert.equal(movementTotal(2026,'movesOut'),19);assert.equal(movementTotal(2026,'mergerIn'),16);assert.equal(movementTotal(2026,'mergerOut'),16);
  const fall=build(people,{term:'fall'});assert.deepEqual(fall.years,[2023,2024,2025]);
  assert.equal(fall.coverage.annual.at(-1).people,3234);
  for(const i of spring.institutions) for(const y of i.years){
    const m=y.movement;assert.equal(y.origins.total,y.count);assert.equal(y.origins.schools.reduce((n,s)=>n+s.count,0),y.count);
    if(m.comparable){assert.equal(m.previousCount+m.added-m.removed,y.count);assert.equal(m.added,m.movesIn+m.mergerIn+m.priorUnobserved+m.ambiguousIn);assert.equal(m.removed,m.movesOut+m.mergerOut+m.nextUnobserved+m.ambiguousOut);}
  }
  assert.ok(!JSON.stringify(spring).includes(people[0].id));
});
