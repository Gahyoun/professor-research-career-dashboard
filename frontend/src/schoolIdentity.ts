/** Explicit university aliases only. Campus and affiliated-hospital labels remain distinct. */
const aliases: [string, string[]][] = [
  ['Seoul National University', ['Seoul', 'SNU']],
  ['Korea Advanced Institute of Science and Technology', ['KAIST']],
  ['Pohang University of Science and Technology', ['POSTECH']],
  ['Korea University', ['Korea']], ['Yonsei University', ['Yonsei']],
  ['University of Oxford', ['Oxford']], ['University of Cambridge', ['Cambridge']],
  ['Massachusetts Institute of Technology', ['MIT']], ['California Institute of Technology', ['Caltech']],
  ['Harvard University', ['Harvard']], ['Stanford University', ['Stanford']],
  ['Brown University', ['Brown']], ['Cornell University', ['Cornell']],
  ['Princeton University', ['Princeton']], ['Yale University', ['Yale']],
  ['Kyoto University', ['Kyoto']], ['The University of Tokyo', ['Tokyo']],
  ['Gwangju Institute of Science and Technology', ['GIST']],
  ['Ulsan National Institute of Science and Technology', ['UNIST']],
  ['Pusan National University', ['Pusan']], ['Kyungpook National University', ['Kyungpook']],
  ['Chungnam National University', ['Chungnam']], ['Chungbuk National University', ['Chungbuk']],
  ['Jeonbuk National University', ['Jeonbuk']], ['Chonnam National University', ['Chonnam']],
  ['Sungkyunkwan University', ['Sungkyunkwan']], ['Sogang University', ['Sogang']],
  ['Ewha Womans University', ['Ewha']], ['Kyung Hee University', ['Kyung-Hee']],
];
const key = (value: string) => value.normalize('NFKC').trim().toLocaleLowerCase('en-US').replace(/\s+/g, ' ');
const lookup = new Map(aliases.flatMap(([canonical, variants]) => [canonical, ...variants].map(name => [key(name), canonical] as const)));
export function canonicalSchool(value: string | null | undefined): string | null {
  if (!value || /^\d+$/.test(value.trim())) return null;
  return lookup.get(key(value)) || value.trim();
}

// Presentation aliases are separate from matching keys and dated university successions.
// Match whole names only: campuses, hospitals and historical institutions stay distinct.
const displayAliases: [string, string[]][] = [
  ...aliases,
  ['Korea Advanced Institute of Science and Technology', ['한국과학기술원']],
  ['Ulsan National Institute of Science and Technology', ['울산과학기술원']],
  ['Daegu Gyeongbuk Institute of Science and Technology', ['DGIST', '대구경북과학기술원']],
  ['Gwangju Institute of Science and Technology', ['광주과학기술원']],
  ['Pohang University of Science and Technology', ['포항공과대학교', '포항공대']],
  ['Seoul National University', ['서울대학교', '서울대']],
  ['Yonsei University', ['연세대학교', '연세대']],
  ['Korea University', ['고려대학교', '고려대']],
  ['Hanyang University', ['Hanyang', '한양대학교', '한양대']],
  ['Kyungpook National University', ['경북대학교', '경북대']],
  ['Pusan National University', ['부산대학교', '부산대']],
  ['Sungkyunkwan University', ['SKKU', '성균관대학교', '성균관대']],
  ['Kyung Hee University', ['Kyung Hee', '경희대학교', '경희대']],
  ['Chonnam National University', ['전남대학교', '전남대']],
  ['Chungnam National University', ['충남대학교', '충남대']],
  ['Chungbuk National University', ['충북대학교', '충북대']],
  ['Chung-Ang University', ['Chung-Ang', 'Chung_Ang', '중앙대학교', '중앙대']],
  ['Ewha Womans University', ['이화여자대학교', '이화여대']],
  ['Sogang University', ['서강대학교', '서강대']],
  ['Jeonbuk National University', ['전북대학교', '전북대']],
  ['Chonbuk National University', ['Chonbuk']],
  ['Gachon University', ['Gachon', '가천대학교', '가천대']],
  ['Gyeongsang National University', ['GNU', 'Gyeongsang', '경상국립대학교', '경상국립대', '경상대학교', '경상대']],
  ['Gyeongnam National University of Science and Technology', ['GNTECH', '경남과학기술대학교', '경남과학기술대', '경남과기대']],
  ['Kangwon National University', ['Kangwon', '강원대학교', '강원대', '강원대학교 (통합)', '통합강원대']],
  ['Gangneung-Wonju National University', ['국립강릉원주대학교', '강릉원주대학교', '강릉원주대']],
  ['The Hong Kong University of Science and Technology', ['HKUST']],
  ['Korea National Open University', ['KNOU', '한국방송통신대학교', '한국방송통신대']],
  ['Korea National University of Education', ['KNUE', '한국교원대학교', '한국교원대']],
  ['Korea National University of Transportation', ['KNUT', '한국교통대학교', '한국교통대']],
  ['Dongguk University WISE Campus', ['Dongguk_wise']],
];
const displayLookup = new Map<string, string>();
const searchAliases = new Map<string, Set<string>>();
for (const [fullName, variants] of displayAliases) {
  const names = searchAliases.get(fullName) || new Set<string>();
  for (const name of [fullName, ...variants]) {
    displayLookup.set(key(name), fullName);
    names.add(name);
  }
  searchAliases.set(fullName, names);
}

/** Full English label only; never use this to decide identity or count membership. */
export function institutionDisplayName(value: string | null | undefined): string {
  if (!value?.trim()) return '정보 없음';
  return displayLookup.get(key(value)) || value.trim();
}

/** Retain Korean names and abbreviations as search terms after relabelling. */
export function institutionSearchText(value: string | null | undefined): string {
  if (!value?.trim()) return '';
  const fullName = institutionDisplayName(value);
  return [...(searchAliases.get(fullName) || [fullName]), value].join(' ');
}
