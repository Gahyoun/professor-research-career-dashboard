import assert from 'node:assert/strict';
import test from 'node:test';
import { buildLifetimeTrajectory } from '../work/test-dist/constellation/lifetime.js';
const unit={institution:'School',country:'KR',department:'Physics'};
const appointment=(start,end,extra={})=>({...unit,start_year:start,end_year:end,role:'faculty',evidence_kind:'official_profile',evidence_status:'verified',...extra});
const student=(id,end,extra={})=>({id,phd_institution:'School',phd_country:'KR',phd_department:'Physics',phd_year:end,...extra});
const stage=(result,id)=>result.stages.find(s=>s.stage===id);
const groups=(records,id='A',options={})=>buildLifetimeTrajectory(records,id,{releaseYear:2026,...options});

test('doctoral group joins overlapping students and verified faculty, never inferred faculty affiliations',()=>{
  const rows=[student('A',2010),student('B',2009),{id:'teacher',faculty_appointments:[appointment(2001,2026)]},
    {id:'not-proof',career:[{...unit,stage:'faculty',position_no:1,confidence:'confirmed',is_estimated:false,start_year:2000,end_year:2026}]}];
  const result=groups(rows),group=stage(result,'doctoral').groups[0];
  assert.deepEqual(group.members,['A','B','teacher']);
  assert.deepEqual(group.memberEvidence.map(e=>[e.peerId,e.peerStage,e.startYear,e.endYear]),[['B','doctoral',2005,2009],['teacher','faculty',2005,2010]]);
  assert.ok(stage(result,'doctoral').excludedReasons.some(reason=>reason.includes('논문 소속')));
});

test('foreign doctoral/faculty units require departments and never use current department fallback',()=>{
  const rows=[student('A',2010,{phd_country:'US'}),student('B',2010,{phd_country:'US',phd_department:'Math'}),
    student('missing',2010,{phd_country:'US',phd_department:null,department:'Physics'}),
    {id:'teacher',faculty_appointments:[appointment(2000,2010,{country:'US',department:null})],department:'Physics'}];
  assert.equal(stage(groups(rows),'doctoral').groups.length,0);
  rows[1].phd_department='Physics';
  assert.deepEqual(stage(groups(rows),'doctoral').groups[0].members,['A','B']);
});

test('postdoc uses institution/time only while excluding unproved faculty roles',()=>{
  const rows=[{id:'A',career:[{...unit,department:null,stage:'postdoc',start_year:2000,end_year:2002,is_estimated:false}]},
    student('B',2003,{phd_department:null}),
    {id:'C',faculty_appointments:[appointment(2001,2002,{department:null})]},
    {id:'D',career:[{...unit,stage:'faculty',start_year:2001,end_year:2002,is_estimated:false}]}];
  const group=stage(groups(rows),'postdoc').groups[0];
  assert.deepEqual(group.members,['A','B','C']);assert.equal(group.department,undefined);
  assert.ok(group.memberEvidence.every(e=>e.inferredDepartment===false));
});

test('first assistant requires explicit rank and first-appointment evidence, not earliest faculty position',()=>{
  const rows=[{id:'A',career:[{...unit,stage:'faculty',position_no:1,rank:'assistant_professor',start_year:2000,end_year:2003,is_estimated:false}],
    faculty_appointments:[appointment(2000,2003,{rank:'assistant_professor'})]},
    {id:'B',faculty_appointments:[appointment(2001,2004)]}];
  assert.equal(stage(groups(rows),'first_faculty').intervals.length,0);
  rows[0].faculty_appointments[0].first_assistant_professor_verified=true;
  const group=stage(groups(rows),'first_faculty').groups[0];
  assert.deepEqual(group.members,['A','B']);assert.equal(group.startYear,2000);assert.equal(group.endYear,2003);
  rows[0].faculty_appointments[0].rank='associate_professor';
  assert.equal(stage(groups(rows),'first_faculty').intervals.length,0);
});

test('conflicting first-assistant institutions remain unavailable instead of choosing one',()=>{
  const extra={rank:'assistant_professor',first_assistant_professor_verified:true};
  const result=groups([{id:'A',faculty_appointments:[appointment(2000,2002,extra),appointment(2001,2003,{...extra,institution:'Other'})]}]);
  assert.equal(stage(result,'first_faculty').intervals.length,0);
  assert.ok(stage(result,'first_faculty').excludedReasons.some(r=>r.includes('충돌')));
});

test('current group needs current-year observations and respects inferred department opt-in',()=>{
  const current={...unit,observation_year:2026,evidence_kind:'semester_roster',evidence_status:'observed',department_inferred:true};
  const rows=[{id:'A',current_position:current},{id:'B',current_position:{...current}},
    {id:'stale',current_position:{...current,observation_year:2025}},
    {id:'no-source',current_institution:'School',current_country:'KR',department:'Physics'}];
  assert.equal(stage(groups(rows),'current').groups.length,0);
  const result=groups(rows,'A',{includeInferredDepartments:true});
  assert.deepEqual(stage(result,'current').groups[0].members,['A','B']);
  assert.ok(stage(groups(rows,'stale',{includeInferredDepartments:true}),'current').excludedReasons.some(r=>r.includes('현재로 연장하지')));
});

test('estimated PhD windows honor options and explicit actual periods have priority',()=>{
  const rows=[student('A',2010),student('B',2015)];
  assert.equal(stage(groups(rows),'doctoral').groups.length,1);
  assert.equal(stage(groups(rows,'A',{estimatedYears:4}),'doctoral').groups.length,0);
  assert.equal(stage(groups(rows,'A',{includeEstimated:false}),'doctoral').groups.length,0);
  rows.forEach(r=>{r.career=[{...unit,stage:'doctoral',start_year:2000,end_year:2002,is_estimated:false}]});
  assert.equal(stage(groups(rows,'A',{includeEstimated:false}),'doctoral').groups[0].estimated,false);
});

test('nonoverlapping observed faculty years never fill employment gaps',()=>{
  const rows=[student('A',2010),{id:'teacher',faculty_appointments:[appointment(2005,2005),appointment(2010,2010)]}];
  const group=stage(groups(rows),'doctoral').groups[0];
  assert.deepEqual(group.memberEvidence.map(e=>[e.startYear,e.endYear]),[[2005,2005],[2010,2010]]);
});

test('stage filters affect groups and peer membership without inventing unavailable stages',()=>{
  const current={...unit,observation_year:2026,evidence_kind:'semester_roster',evidence_status:'observed'};
  const rows=[student('A',2010,{current_position:current}),student('B',2010),{id:'C',current_position:current}];
  assert.deepEqual(groups(rows,'A',{stages:['current']}).peers.map(p=>p.id),['C']);
  assert.equal(groups(rows,'A',{stages:[]}).peers.length,0);
  assert.equal(groups(rows,'absent').selectedFound,false);
});

test('raw identity fields and URLs never enter graph evidence; duplicate identities are deduplicated',()=>{
  const a=student('A',2010,{name:'SECRET NAME'}), b={id:'B',faculty_appointments:[{...appointment(2000,2010),source_url:'https://SECRET.example/person'}]};
  const result=groups([a,a,b,b]);assert.equal(result.peers.length,1);
  assert.ok(!JSON.stringify(result).includes('SECRET'));
});

test('actual doctoral unit conflicts cannot borrow the degree department and malformed IDs are ignored',()=>{
  const a=student('A',2010,{career:[{stage:'doctoral',institution_canonical:'Other',country:'KR',start_year:2005,end_year:2010,is_estimated:false}]});
  const b=student('B',2010,{phd_institution:'Other'});
  assert.equal(stage(groups([a,b]),'doctoral').groups.length,0);
  a.career[0].institution_canonical='School';a.career[0].country='US';b.phd_institution='School';b.phd_country='US';
  assert.equal(stage(groups([a,b]),'doctoral').groups.length,0);
  const result=groups([student('A',2010),student('B',2010),student(' ',2010),student(7,2010)]);
  assert.deepEqual(result.peers.map(p=>p.id),['B']);
});
