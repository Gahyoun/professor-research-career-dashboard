import assert from 'node:assert/strict';
import test from 'node:test';
import { buildHypergraph as buildCoreHypergraph, layoutHypergraph, normalizeInstitution, institutionKey, findTrajectoryPeers, buildResearcherTrajectory } from '../work/test-dist/constellation/hypergraph.js';
const buildHypergraph=(records,options={})=>buildCoreHypergraph(records,{cohortEnabled:false,...options});

const person = (id, institution, phd_year, career = []) => ({ id, subject: 'Physics', phd_institution: institution, phd_country: 'US', bachelor_country:'US', phd_year, career });
const actual = (start, end) => ({ stage: 'PhD', start_year: start, end_year: end, is_estimated: false });
const commonYears = graph => graph.edges.filter(e => e.kind === 'temporal').flatMap(e => e.years).sort((a,b) => a-b);

test('inclusive annual endpoint overlap and no overlap across adjacent years', () => {
  const graph = buildHypergraph([person('a', null, 2010), person('b', null, 2015), person('c', null, 2021)]);
  assert.deepEqual(commonYears(graph), [2010]);
  assert.deepEqual(graph.edges[0].members, [0,1]);
  assert.equal(graph.diagnostics.isolatedCount, 1);
});

test('actual doctoral intervals take priority and postdoctoral intervals do not count', () => {
  const graph = buildHypergraph([
    person('a', null, 2020, [actual(2000, 2002)]),
    person('b', null, null, [actual(2002, 2004)]),
    person('c', null, 2010, [{ ...actual(2000, 2005), stage: 'postdoc' }]),
  ]);
  assert.deepEqual(commonYears(graph), [2002]);
  assert.equal(graph.diagnostics.actualTimeCount, 2);
  assert.equal(graph.diagnostics.estimatedCount, 1);
  assert.equal(graph.timeWindows[0].startYear, 2000);
});

test('estimated career rows are replaced by configurable estimation; exclusion is explicit', () => {
  const records = [person('a', null, 2010, [{ ...actual(1990, 1998), is_estimated: true }]), person('b', null, 2014)];
  assert.deepEqual(commonYears(buildHypergraph(records, { estimatedYears: 3 })), []);
  assert.deepEqual(commonYears(buildHypergraph(records, { estimatedYears: 4 })), [2010]);
  const excluded = buildHypergraph(records, { includeEstimated: false });
  assert.equal(excluded.edges.length, 0);
  assert.equal(excluded.diagnostics.excludedEstimatedCount, 2);
  assert.equal(excluded.diagnostics.estimatedCount, 0);
});

test('unknown dates stay missing and malformed actual intervals cannot create artificial cohorts', () => {
  const graph = buildHypergraph([person('a', null, null), person('b', null, NaN), person('c', null, null, [actual(2010, 2005)])]);
  assert.equal(graph.edges.length, 0);
  assert.equal(graph.diagnostics.missingTimeCount, 3);
  assert.equal(graph.diagnostics.invalidIntervalsCount, 1);
});

test('institution normalization is conservative and missing values never form edges', () => {
  assert.equal(normalizeInstitution(' ＭＩＴ. '), 'mit');
  for (const missing of [null, '', 'N/A', 'UNKNOWN', '미상', '정보 없음', 'nan', '-', '101', '１１２']) assert.equal(normalizeInstitution(missing), null);
  const graph = buildHypergraph([person('a', ' MIT. ', null), person('b', 'mit', null), person('c', 'Unknown', null), person('d', 'unknown', null)]);
  assert.equal(graph.edges.length, 1);
  assert.deepEqual(graph.edges[0].members, [0,1]);
  assert.equal(graph.diagnostics.missingInstitutionCount, 2);
});

test('bachelor institution choice, layer toggles, and zero layer weights are honored', () => {
  const records = [person('a', 'A', 2010), person('b', 'B', 2010)].map(record => ({ ...record, bachelor_institution: 'Shared' }));
  assert.equal(buildHypergraph(records, { institutionLevel:'bachelor', temporalEnabled:false }).edges.length, 1);
  assert.equal(buildHypergraph(records, { spatialEnabled:false, temporalWeight:0 }).edges.length, 0);
});

test('duplicate IDs are excluded and personal record fields never propagate', () => {
  const graph = buildHypergraph([{ ...person('a', 'A', 2010), name: 'PRIVATE NAME', url:'PRIVATE URL' }, person('a', 'B', 2015), person('b', 'A', 2010)]);
  assert.equal(graph.nodes.length, 2);
  assert.equal(graph.diagnostics.duplicateIdsCount, 1);
  assert.deepEqual(Object.keys(graph.nodes[0]).sort(), ['id','layoutYear','subject']);
  assert.ok(!JSON.stringify(graph).includes('PRIVATE'));
  assert.deepEqual(graph.edges.find(e=>e.kind==='spatial').members,[0,1]);
});

test('identical annual memberships merge without multiplying weight and preserve years', () => {
  const graph = buildHypergraph([person('a',null,2010), person('b',null,2010)], {spatialEnabled:false});
  assert.equal(graph.edges.length, 1);
  assert.deepEqual(graph.edges[0].years,[2005,2006,2007,2008,2009,2010]);
  assert.equal(graph.edges[0].label,'2005–2010');
  assert.equal(graph.edges[0].weight,2);
  assert.equal(graph.diagnostics.mergedTemporalSetCount,5);
});

test('noncontiguous actual intervals do not silently fill gaps', () => {
  const careers = [actual(2000,2001),actual(2004,2005)];
  const graph=buildHypergraph([person('a',null,null,careers),person('b',null,null,careers)]);
  assert.deepEqual(graph.edges[0].years,[2000,2001,2004,2005]);
  assert.equal(graph.edges[0].label,'2000–2001, 2004–2005');
});

test('large edges have lower size weight and overlapping time sets have Jaccard correction', () => {
  const graph=buildHypergraph([person('a','A',null),person('b','A',null),person('c','B',null),person('d','B',null),person('e','B',null)]);
  assert.equal(graph.edges[0].weight,2);
  assert.equal(graph.edges[1].weight,1.5);
  const temporal=buildHypergraph([person('a',null,null,[actual(2000,2001)]),person('b',null,null,[actual(2000,2000)]),person('c',null,null,[actual(2001,2001)])]);
  for(const edge of temporal.edges) assert.ok(Math.abs(edge.overlapAdjustment-0.75)<1e-10);
  const both=buildHypergraph([person('a','A',2010),person('b','A',2010)]);
  assert.equal(both.edges[0].overlapAdjustment,1);
  assert.equal(both.edges[1].overlapAdjustment,1);
});

test('domestic same-school different departments never match; foreign department differences are ignored', () => {
  assert.notEqual(institutionKey({institution:'Seoul National University',country:'KR',department:'Physics'}),institutionKey({institution:'Seoul National University',country:'Korea',department:'Mathematics'}));
  assert.equal(institutionKey({institution:'Oxford',country:'GB',department:'Mathematics'}),institutionKey({institution:'Oxford',country:'United Kingdom',department:'Mathematical Institute'}));
  assert.equal(institutionKey({institution:'Oxford',country:null,department:'Mathematics'}),null);
  assert.equal(institutionKey({institution:'Seoul National University',country:'KR'}),null);
  const records=[
    {...person('a','SNU',null),phd_country:'KR',phd_department:'Physics'},
    {...person('b','SNU',null),phd_country:'KR',phd_department:'Math'},
    {...person('c','SNU',null),phd_country:'KR',phd_department:'Physics'},
    {...person('d','SNU',null),phd_country:'KR',department:'Physics'},
    {...person('e','Unknown Country School',null),phd_country:null},
  ];
  const graph=buildHypergraph(records);
  assert.equal(graph.edges.length,1);
  assert.deepEqual(graph.edges[0].members,[0,2]);
  assert.equal(graph.diagnostics.missingDepartmentCount,1);
  assert.equal(graph.diagnostics.missingCountryCount,1);
});

test('inferred domestic departments are opt-in and explicitly marked', () => {
  const records=['a','b'].map(id=>({...person(id,'SNU',null),phd_country:'KR',phd_department:'Physics',phd_department_inferred:true}));
  assert.equal(buildHypergraph(records).edges.length,0);
  assert.equal(buildHypergraph(records).diagnostics.excludedInferredDepartmentCount,2);
  const allowed=buildHypergraph(records,{includeInferredDepartments:true});
  assert.equal(allowed.edges[0].inferredDepartment,true);
  assert.equal(allowed.diagnostics.inferredDepartmentCount,2);
});

test('verified canonical school aliases match without guessed aliases', () => {
  assert.equal(institutionKey({institution:'U. Oxford',institution_canonical:'University of Oxford',country:'GB'}),institutionKey({institution:'Oxford',institution_canonical:'University of Oxford',country:'GB'}));
  assert.notEqual(institutionKey({institution:'U. Oxford',country:'GB'}),institutionKey({institution:'Oxford',country:'GB'}));
});

test('bachelor cohort uses only phd_year−10..−8 inclusive, and estimated exclusion suppresses it', () => {
  const records=[person('a','X',2010),person('b','X',2012),person('c','X',2013)].map(r=>({...r,bachelor_institution:'Oxford',bachelor_country:'GB'}));
  const graph=buildHypergraph(records,{bachelorTemporalEnabled:true,temporalEnabled:false,cohortEnabled:true});
  const cohort=graph.edges.find(e=>e.kind==='cohort'&&e.degree==='bachelor'&&e.years.includes(2002));
  assert.deepEqual(cohort.members,[0,1]);
  assert.deepEqual(graph.timeWindows.find(w=>w.nodeIndex===0&&w.degree==='bachelor'),{nodeIndex:0,startYear:2000,endYear:2002,estimated:true,degree:'bachelor'});
  assert.equal(buildHypergraph(records,{bachelorTemporalEnabled:true,includeEstimated:false,cohortEnabled:true}).edges.some(e=>e.degree==='bachelor'),false);
});

test('joint cohorts require eligible school+department and overlapping degree years', () => {
  const records=[
    {...person('a','SNU',2010),phd_country:'KR',phd_department:'Physics'},
    {...person('b','SNU',2012),phd_country:'KR',phd_department:'Physics'},
    {...person('c','SNU',2010),phd_country:'KR',phd_department:'Math'},
    {...person('d','SNU',2025),phd_country:'KR',phd_department:'Physics'},
  ];
  const graph=buildHypergraph(records,{cohortEnabled:true});
  const cohorts=graph.edges.filter(e=>e.kind==='cohort');
  assert.equal(cohorts.length,1);assert.deepEqual(cohorts[0].members,[0,1]);
  assert.deepEqual(cohorts[0].years,[2007,2008,2009,2010]);
  assert.equal(cohorts[0].degree,'phd');
});

test('chronological lane layout separates distant graduation cohorts in vertical order', () => {
  const graph=buildHypergraph(Array.from({length:40},(_,i)=>person(`p${i}`,'Oxford',1980+Math.floor(i/10)*10)));
  const result=layoutHypergraph(graph,{chronologicalStrength:.35,minDistance:4});
  const means=[0,1,2,3].map(group=>result.positions.slice(group*10,group*10+10).reduce((sum,p)=>sum+p.y,0)/10);
  assert.ok(means.every((mean,i)=>i===0||mean>means[i-1]+50));
});

test('trajectory score is deduplicated unit-year Jaccard with stage/year evidence', () => {
  const faculty=(start,end,department='Physics',country='KR')=>({stage:'faculty',institution:'SNU',country,department,start_year:start,end_year:end,is_estimated:false});
  const records=[person('a',null,null,[faculty(2000,2002),faculty(2001,2002)]),person('b',null,null,[faculty(2002,2004)]),person('c',null,null,[faculty(2000,2002,'Math')])];
  const result=findTrajectoryPeers(records,'a');
  assert.equal(result.peers.length,1);
  assert.equal(result.peers[0].id,'b');
  assert.equal(result.peers[0].sharedUnitYears,1);
  assert.equal(result.peers[0].unionUnitYears,5);
  assert.equal(result.peers[0].jaccard,0.2);
  assert.equal(result.peers[0].evidence[0].startYear,2002);
  assert.equal(result.peers[0].evidence[0].selectedStage,'faculty');
  assert.equal(result.selectedCoverage.unitYears,3);
});

test('trajectory matches foreign school across department labels and distinguishes stages', () => {
  const records=[person('a',null,null,[{stage:'postdoc',institution:'Oxford',country:'GB',department:'Math',start_year:2000,end_year:2002,is_estimated:false}]),person('b','Oxford',2003,[actual(2002,2003)])];
  records[1].phd_country='GB';
  records[1].phd_department='Mathematical Institute';
  const result=findTrajectoryPeers(records,'a');
  assert.equal(result.peers[0].sharedUnitYears,1);
  assert.equal(result.peers[0].unionUnitYears,4);
  assert.equal(result.peers[0].evidence[0].selectedStage,'postdoc');
  assert.equal(result.peers[0].evidence[0].peerStage,'doctoral');
  assert.equal(result.peers[0].evidence[0].estimated,false);
});

test('trajectory unknown units, estimated exclusion, inferred exclusion and duplicate peers remain conservative', () => {
  const records=['a','b'].map(id=>({...person(id,'SNU',2010),phd_country:'KR',phd_department:'Physics',phd_department_inferred:true}));
  assert.equal(findTrajectoryPeers(records,'a').peers.length,0);
  assert.equal(findTrajectoryPeers(records,'a',{includeInferredDepartments:true,includeEstimated:false}).peers.length,0);
  const allowed=findTrajectoryPeers([...records,records[1]],'a',{includeInferredDepartments:true});
  assert.equal(allowed.peers.length,1);
  assert.equal(allowed.peers[0].score,1);
  assert.equal(allowed.peers[0].evidence[0].estimated,true);
  assert.equal(allowed.peers[0].evidence[0].inferredDepartment,true);
  const unknown=buildResearcherTrajectory(person('u',null,null,[{stage:'faculty',institution:'Oxford',country:null,department:'Math',start_year:2000,end_year:2002,is_estimated:false}]));
  assert.equal(unknown.coverage.missingCountryIntervals,1);
  assert.equal(unknown.intervals.length,0);
  assert.equal(findTrajectoryPeers(records,'absent').selectedFound,false);
});

test('disconnected components, isolated nodes, empty and singleton graphs produce deterministic finite layouts', () => {
  const records=[...Array.from({length:12},(_,i)=>person(`a${i}`,'A',null)),...Array.from({length:8},(_,i)=>person(`b${i}`,'B',null)),...Array.from({length:6},(_,i)=>person(`i${i}`,null,null))];
  const graph=buildHypergraph(records);
  const first=layoutHypergraph(graph), second=layoutHypergraph(graph);
  assert.deepEqual(first.positions,second.positions);
  assert.equal(first.diagnostics.components,8);
  assert.equal(first.diagnostics.collisionPairs,0);
  assert.ok(first.positions.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)));
  assert.deepEqual(layoutHypergraph(buildHypergraph([])).positions,[]);
  assert.equal(layoutHypergraph(buildHypergraph([person('x',null,null)])).positions.length,1);
});

test('spatial-vs-temporal weights change the embedding and best candidate objective is selected', () => {
  const records=Array.from({length:60},(_,i)=>person(`p${i}`,`Inst${i%5}`,1995+Math.floor(i/4)));
  const spatial=layoutHypergraph(buildHypergraph(records,{spatialWeight:10,temporalWeight:1}));
  const temporal=layoutHypergraph(buildHypergraph(records,{spatialWeight:1,temporalWeight:10}));
  assert.ok(spatial.positions.some((p,i)=>Math.hypot(p.x-temporal.positions[i].x,p.y-temporal.positions[i].y)>5));
  assert.ok(spatial.diagnostics.objective<=Math.min(...spatial.diagnostics.candidateObjectives)+1e-10);
  assert.equal(spatial.diagnostics.collisionPairs,0);
});

test('3937-node workload has exact incidence, finite positions, deterministic output and no final node collisions', () => {
  const records=Array.from({length:3937},(_,i)=>person(`anon${String(i).padStart(4,'0')}`,i%29===0?null:`Inst${i%173}`,i%31===0?null:1970+((i*23)%53)));
  const start=performance.now();
  const graph=buildHypergraph(records);
  const result=layoutHypergraph(graph,{width:1400,height:1000,minDistance:9});
  const elapsed=performance.now()-start;
  assert.equal(result.positions.length,3937);
  assert.equal(graph.incidence.reduce((a,b)=>a+b.length,0),graph.edges.reduce((a,b)=>a+b.members.length,0));
  assert.equal(result.diagnostics.collisionPairs,0);
  assert.ok(result.positions.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.x>=44&&p.x<=1356&&p.y>=44&&p.y<=956));
  // Independent sweep verifies the collision diagnostic without copying the hash implementation.
  const sorted=[...result.positions].sort((a,b)=>a.x-b.x);
  for(let i=0;i<sorted.length;i++)for(let j=i+1;j<sorted.length&&sorted[j].x-sorted[i].x<9;j++)assert.ok(Math.hypot(sorted[i].x-sorted[j].x,sorted[i].y-sorted[j].y)>=9-1e-7);
  console.log(JSON.stringify({benchmark:'3937 researchers',elapsedMs:Math.round(elapsed),edges:graph.edges.length,incidence:graph.diagnostics.incidenceCount,components:result.diagnostics.components,collisionPairs:result.diagnostics.collisionPairs}));
  assert.ok(elapsed<6000,`3937-node build+layout unexpectedly slow: ${elapsed} ms`);
});
