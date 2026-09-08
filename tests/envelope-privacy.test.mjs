import assert from 'node:assert/strict';
import test from 'node:test';
import { bubbleEnvelope } from '../work/test-dist/constellation/envelope.js';
import { decryptNameMap } from '../work/test-dist/privacy.js';
import { mergeMetadata } from '../work/test-dist/metadata.js';
import { canonicalSchool } from '../work/test-dist/schoolIdentity.js';

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
