import assert from 'node:assert/strict';
import test from 'node:test';
import { bubbleEnvelope } from '../work/test-dist/constellation/envelope.js';
import { decryptNameMap } from '../work/test-dist/privacy.js';
import { mergeMetadata } from '../work/test-dist/metadata.js';
import { canonicalSchool } from '../work/test-dist/schoolIdentity.js';
import { institutionKey } from '../work/test-dist/constellation/hypergraph.js';
import { buildLifetimeTrajectory } from '../work/test-dist/constellation/lifetime.js';

function inside(p, ring) { let result = false; for (let i=0,j=ring.length-1;i<ring.length;j=i++) { const a=ring[i],b=ring[j]; if ((a.y>p.y)!==(b.y>p.y) && p.x<(b.x-a.x)*(p.y-a.y)/(b.y-a.y)+a.x) result=!result; } return result; }
test('lumpy envelope encloses every member and preserves the empty middle of a U-shaped group', () => {
  const points = [{x:0,y:0},{x:0,y:50},{x:0,y:100},{x:50,y:100},{x:100,y:100},{x:100,y:50},{x:100,y:0}];
  const result = bubbleEnvelope(points, 15, 3);
  for (const point of points) assert.ok(result.rings.some(r => inside(point,r)));
  assert.ok(!result.rings.some(r => inside({x:50,y:20},r)), 'must not collapse to a convex hull');
  assert.ok(result.path.includes('Q')); assert.ok(!/NaN|Infinity/.test(result.path));
  assert.equal(bubbleEnvelope([]).path, '');
});
test('explicit university aliases merge while regional campuses and research organizations stay distinct', () => {
  assert.equal(canonicalSchool('Seoul'), canonicalSchool('Seoul National University'));
  assert.equal(canonicalSchool('Oxford'), canonicalSchool('University of Oxford'));
  assert.notEqual(canonicalSchool('Oxford Research Group'), canonicalSchool('Oxford'));
  assert.notEqual(canonicalSchool('Korea University (Sejong Campus)'), canonicalSchool('Korea'));
  assert.equal(canonicalSchool('101'), null);
});
test('reviewed roster aliases use the same matching keys as full school names without collapsing campuses or hospitals', () => {
  for (const [short, full] of [
    ['Hanyang', 'Hanyang University'], ['Inha', 'Inha University'], ['Dankuk', 'Dankook University'],
    ['Ulsan', 'University of Ulsan'], ['Chung_Ang', 'Chung-Ang University'],
    ['Korea_sejong', 'Korea University (Sejong Campus)'], ['Konkuk_glocal', 'Konkuk University (GLOCAL Campus)'],
    ['Hanyang_ERICA', 'Hanyang University (ERICA Campus)'], ['Yonsei_Mirae', 'Yonsei University (Mirae Campus)'],
    ['Donggkuk_wise', 'Dongguk University (WISE Campus)'], ['KMOU', 'Korea Maritime and Ocean University'],
    ['Gangneung–Wonju National University', 'Gangneung-Wonju National University'],
  ]) assert.equal(canonicalSchool(short), canonicalSchool(full));
  for (const [a, b] of [
    ['Korea_sejong', 'Korea'], ['Konkuk_glocal', 'Konkuk University'], ['Hanyang_ERICA', 'Hanyang'],
    ['Yonsei_Mirae', 'Yonsei'], ['Donggkuk_wise', 'Dongguk University'], ['Ulsan', 'UNIST'],
    ['Hanyang University Seoul Hospital', 'Hanyang'], ['Stanford Medicine', 'Stanford'],
    ['Daegu Techno Park', 'Daegu University'], ['Andong', 'Gyeongkuk National University'],
    ['Gangneung-Wonju National University', 'Kangwon National University'],
    ['Gyeongnam National University of Science and Technology', 'Gyeongsang National University'],
  ]) assert.notEqual(canonicalSchool(a), canonicalSchool(b));
  for (const unresolved of ['CIT', 'IIT', 'IIT@MIT', 'UST', 'KNUST', 'KAUST', 'Myongi', 'Konju', 'Deagu']) {
    assert.equal(canonicalSchool(unresolved), unresolved);
  }
});
test('source canonical disagreements never replace public degree or career institution anchors', () => {
  for (const [school, misleading] of [
    ['Stanford', 'Stanford Medicine'], ['Daegu Techno Park', 'Daegu University'],
    ['Ewha Womans University', 'Hanyang University'],
    ['University of Iowa', 'Iowa State University'],
    ['Seoul National University', 'Seoul National University of Science and Technology'],
  ]) {
    const person = { id: 'P-AAAAAAAAAA', phd_institution: school, bachelor_institution: school,
      department: 'Current department must not replace degree evidence', career: [{ institution: school, start_year: 2000, end_year: 2005 }] };
    const supplement = { phd_institution_canonical: misleading, phd_country: 'KR',
      phd_department: 'Department of Physics', phd_department_inferred: true,
      bachelor_institution_canonical: misleading, bachelor_department: 'Department of Physics', bachelor_department_inferred: true,
      career_units: [{ segment_index: 0, institution: school, institution_canonical: misleading,
        start_year: 2000, end_year: 2005, country: 'KR', department: 'Department of Physics', department_inferred: true }] };
    const joined = mergeMetadata({ professors: [person] }, { [person.id]: supplement }).professors[0];
    assert.equal(joined.phd_institution_canonical, canonicalSchool(school));
    assert.equal(joined.career[0].institution_canonical, canonicalSchool(school));
    assert.notEqual(joined.phd_institution_canonical, canonicalSchool(misleading));
    assert.equal(joined.phd_department, null); assert.equal(joined.bachelor_department, null);
    assert.equal(joined.career[0].department, null); assert.equal(joined.phd_department_inferred, false);
    assert.match(joined.phd_department_evidence, /동일성이 확인되지 않아/);
    assert.match(joined.career[0].department_evidence, /동일성이 확인되지 않아/);
    assert.equal(supplement.phd_department, 'Department of Physics', 'the source supplement is unchanged');
  }
});
test('matching canonical aliases preserve institution-bound inferred and verified department evidence', () => {
  for (const [source, school] of [
    ['Korea', 'Korea University'], ['ＫＡＩＳＴ．', 'Korea Advanced Institute of Science and Technology'],
    ['Hanyang_ERICA', 'Hanyang University (ERICA Campus)'],
    ['Gangneung–Wonju National University', 'Gangneung-Wonju National University'],
  ]) for (const inferred of [true, false]) {
    const person = { id: 'P-AAAAAAAAAA', phd_institution: school, bachelor_institution: school,
      career: [{ institution: school, start_year: 2000, end_year: 2005 }] };
    const evidence = inferred ? 'kept_author_affiliation_same_institution_and_period' : 'verified_degree_record';
    const supplement = { phd_institution_canonical: source, phd_department: 'Department of Physics',
      phd_department_inferred: inferred, phd_department_evidence: evidence,
      bachelor_institution_canonical: source, bachelor_department: 'Department of Physics',
      bachelor_department_inferred: inferred, bachelor_department_evidence: evidence,
      career_units: [{ segment_index: 0, institution: school, institution_canonical: source, start_year: 2000, end_year: 2005,
        department: 'Department of Physics', department_inferred: inferred, department_evidence: evidence }] };
    const joined = mergeMetadata({ professors: [person] }, { [person.id]: supplement }).professors[0];
    assert.equal(joined.phd_department, 'Department of Physics');
    assert.equal(joined.bachelor_department, 'Department of Physics');
    assert.equal(joined.career[0].department, 'Department of Physics');
    assert.equal(joined.phd_department_inferred, inferred); assert.equal(joined.phd_department_evidence, evidence);
    assert.equal(joined.career[0].department_inferred, inferred); assert.equal(joined.career[0].department_evidence, evidence);
  }
});
test('missing, unresolved or numeric source institution anchors cannot transfer department evidence', () => {
  for (const source of [undefined, null, '', 'Unknown', '101', 'Unreviewed abbreviation']) {
    const person = { id: 'P-AAAAAAAAAA', phd_institution: 'Korea University', department: 'Current Physics',
      career: [{ institution: 'Korea University', start_year: 2000, end_year: 2005 }] };
    const supplement = { phd_institution_canonical: source, phd_department: 'Department of Physics',
      phd_department_inferred: false, phd_department_evidence: 'verified_degree_record',
      career_units: [{ segment_index: 0, institution: 'Korea University', institution_canonical: source,
        start_year: 2000, end_year: 2005, department: 'Department of Physics', department_inferred: true }] };
    const joined = mergeMetadata({ professors: [person] }, { [person.id]: supplement }).professors[0];
    assert.equal(joined.phd_institution_canonical, 'Korea University', 'the public school remains usable without the supplement anchor');
    assert.equal(joined.phd_department, null); assert.equal(joined.career[0].department, null);
    assert.match(joined.phd_department_evidence, /동일성/);
  }
});
test('matching aliases preserve department, country, time and first-assistant evidence requirements', () => {
  const faculty = (id, changes = {}) => ({ id, career: [], faculty_appointments: [{
    institution: 'Hanyang', institution_canonical: canonicalSchool('Hanyang'), country: 'KR',
    department: 'Department of Physics', start_year: 2004, end_year: 2004,
    role: 'faculty', rank: 'assistant_professor', evidence_kind: 'semester_roster', evidence_status: 'observed', ...changes,
  }] });
  const selected = { id: 'P-AAAAAAAAAA', phd_institution: 'Hanyang University', phd_year: 2005,
    phd_country: 'KR', phd_department: 'Department of Physics', career: [] };
  const records = [selected, faculty('P-BBBBBBBBBB'),
    faculty('P-CCCCCCCCCC', { department: 'Department of Mathematics' }),
    faculty('P-DDDDDDDDDD', { country: 'US' }), faculty('P-EEEEEEEEEE', { country: null }),
    faculty('P-FFFFFFFFFF', { department: null }), faculty('P-GGGGGGGGGG', { start_year: 2006, end_year: 2006 })];
  const result = buildLifetimeTrajectory(records, selected.id, { releaseYear: 2026, includeEstimated: true });
  assert.deepEqual(result.peers.map(p => p.id), ['P-BBBBBBBBBB']);
  const first = buildLifetimeTrajectory(records, 'P-BBBBBBBBBB', { releaseYear: 2026 });
  assert.equal(first.stages.find(s => s.id === 'first_faculty').intervals.length, 0);
  assert.equal(institutionKey({ institution_canonical: canonicalSchool('Dankuk'), country: null, department: null }), null);
});
test('supplement join rejects stale segment identities and never substitutes current department', () => {
  const data = { professors: [{id:'P-AAAAAAAAAA',department:'Current Physics',phd_institution:'SNU',career:[{institution:'School',start_year:2000,end_year:2005}]}] };
  const metadata = {'P-AAAAAAAAAA': {phd_country:'KR',phd_department:null,career_units:[{segment_index:0,institution:'School',start_year:2000,end_year:2005,country:'KR',department:null}]}};
  const joined = mergeMetadata(data,metadata);
  assert.equal(joined.professors[0].phd_department,null); assert.equal(joined.professors[0].career[0].department,null);
  assert.equal(data.professors[0].phd_department,undefined);
  metadata['P-AAAAAAAAAA'].career_units[0].end_year=2006;
  assert.throws(()=>mergeMetadata(data,metadata),/career mismatch/);
  assert.throws(()=>mergeMetadata(data,{}),/researcher mismatch/);
});
test('synthetic encrypted names require the correct password and authenticated, well-formed plaintext', async () => {
  const password='SYNTHETIC-ONLY-NOT-A-REAL-PASSWORD', salt=crypto.getRandomValues(new Uint8Array(16)), nonce=crypto.getRandomValues(new Uint8Array(12)), aad=new TextEncoder().encode('synthetic-test');
  const material=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveKey']);
  const key=await crypto.subtle.deriveKey({name:'PBKDF2',salt,iterations:600000,hash:'SHA-256'},material,{name:'AES-GCM',length:256},false,['encrypt']);
  const b64=x=>Buffer.from(x).toString('base64');
  const seal=async plaintext=>({iterations:600000,salt:b64(salt),nonce:b64(nonce),aad:b64(aad),ciphertext:b64(await crypto.subtle.encrypt({name:'AES-GCM',iv:nonce,additionalData:aad},key,new TextEncoder().encode(JSON.stringify(plaintext))))});
  const names={'P-AAAAAAAAAA':'Synthetic researcher'};
  const envelope=await seal(names);
  assert.deepEqual(await decryptNameMap(password,envelope),names);
  await assert.rejects(()=>decryptNameMap('incorrect',envelope));
  await assert.rejects(()=>decryptNameMap(password,{...envelope,aad:b64(new TextEncoder().encode('tampered'))}));
  await assert.rejects(async ()=>decryptNameMap(password,await seal([])),/Invalid name map/);
});
