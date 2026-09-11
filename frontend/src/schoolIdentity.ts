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
  // Reviewed source spellings; see docs/INSTITUTION_LABELS.md for evidence.
  ['University of Illinois Urbana-Champaign', [
    'University of Illinois at Urbana-Champaign', 'University of Illinois at Urbana - Champaign',
    'Illinois at Urbana - Champaign', 'Illinois-Urbana/Champaign',
  ]],
  ['University of Illinois Chicago', ['University of Illinois at Chicago', 'Illinois at Chicago']],
  ['University of Wisconsin–Madison', ['University of Wisconsin-Madison', 'Wisconsin-Madison', 'Wisconsin–Madison']],
  ['Colorado School of Mines', ['Colorado School of Mines.']],
  ['Sri Venkateswara University', ['Sri Venkateswara Physics']],
  ['Kyoto University', ['Kyoto']], ['The University of Tokyo', ['Tokyo']],
  ['Gwangju Institute of Science and Technology', ['GIST']],
  ['Ulsan National Institute of Science and Technology', ['UNIST']],
  ['Pusan National University', ['Pusan']], ['Kyungpook National University', ['Kyungpook']],
  ['Chungnam National University', ['Chungnam']], ['Chungbuk National University', ['Chungbuk']],
  ['Jeonbuk National University', ['Jeonbuk']], ['Chonnam National University', ['Chonnam']],
  ['Sungkyunkwan University', ['Sungkyunkwan']], ['Sogang University', ['Sogang']],
  ['Ewha Womans University', ['Ewha']], ['Kyung Hee University', ['Kyung-Hee']],
  // Reviewed public-school / roster aliases. These are explicit identities,
  // not the presentation lookup or a crosswalk learned from source canonicals:
  // source canonicals also contain hospitals and conflicting school assignments.
  ['Hanyang University', ['Hanyang']], ['Inha University', ['Inha']],
  ['Chung-Ang University', ['Chung-Ang', 'Chung_Ang']],
  ['Dankook University', ['Dankuk', 'Dankook']],
  ['University of Ulsan', ['Ulsan']],
  ['Kumoh National Institute of Technology', ['Kumoh']],
  ['Kosin University', ['Kosin']], ['Seokyeong University', ['Seokyeong']],
  ['Dongshin University', ['Dongshin']], ['Wonkwang University', ['Wonkwang']],
  ['Inje University', ['Inje']], ['Andong National University', ['Andong']],
  ['Daegu Haany University', ['Daegu Haany']], ['Jungwon University', ['Jungwon']],
  ['Korea Maritime and Ocean University', ['KMOU']],
  ['Korea University (Sejong Campus)', ['Korea_sejong', 'Korea-Sejong']],
  ['Konkuk University (GLOCAL Campus)', ['Konkuk_glocal']],
  ['Hanyang University (ERICA Campus)', ['Hanyang_ERICA', 'Hanyang-ERICA']],
  ['Yonsei University (Mirae Campus)', ['Yonsei_Mirae', 'Yonsei-Mirae']],
  ['Dongguk University (WISE Campus)', ['Dongguk University WISE Campus', 'Dongguk_wise', 'Donggkuk_wise']],
  ['Gangneung-Wonju National University', ['Gangneung–Wonju National University']],
  ['Daegu Catholic University', ['Daegu Catholic']],
  ['Sangmyung University', ['Sangmyung']], ['Seowon University', ['Seowon']],
  ['Kyungnam University', ['Kyungnam']], ['Hongik University', ['Hongik']],
  ['Korea National Open University', ['KNOU']],
  ['Korea National University of Education', ['KNUE']],
  ['Korea National University of Transportation', ['KNUT']],
  ['The Hong Kong University of Science and Technology', ['HKUST']],
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
  ['Dongguk University (WISE Campus)', ['Dongguk University WISE Campus', 'Dongguk_wise', 'Donggkuk_wise', '동국대학교 WISE캠퍼스']],
  ['Dankook University', ['Dankuk', 'Dankook', '단국대학교', '단국대']],
  ['Korea University (Sejong Campus)', ['Korea_sejong', 'Korea-Sejong', '고려대학교 세종캠퍼스', '고려대 세종']],
  ['Konkuk University (GLOCAL Campus)', ['Konkuk_glocal', '건국대학교 글로컬캠퍼스', '건국대 글로컬']],
  ['Hanyang University (ERICA Campus)', ['Hanyang_ERICA', 'Hanyang-ERICA', '한양대학교 ERICA캠퍼스', '한양대 에리카']],
  ['Yonsei University (Mirae Campus)', ['Yonsei_Mirae', 'Yonsei-Mirae', '연세대학교 미래캠퍼스', '연세대 미래']],
  ['University of Ulsan', ['Ulsan', '울산대학교', '울산대']],
  ['Ajou University', ['Ajou', '아주대학교', '아주대']],
  ['CHA University', ['Cha', '차의과학대학교']],
  ['Cheongju University', ['Cheongju', '청주대학교', '청주대']],
  ['Daegu Haany University', ['Daegu Haany', '대구한의대학교', '대구한의대']],
  ['Dong-A University', ['Dong_A', 'Dong-A', '동아대학교', '동아대']],
  ['Dongguk University', ['Dongguk', '동국대학교', '동국대']],
  ['Dongshin University', ['Dongshin', '동신대학교', '동신대']],
  ['Hallym University', ['Hallym', '한림대학교', '한림대']],
  ['Hankyong National University', ['Hankyong', '한경국립대학교', '한경대학교', '한경대']],
  ['Hannam University', ['Hannam', '한남대학교', '한남대']],
  ['Inha University', ['Inha', '인하대학교', '인하대']],
  ['Inje University', ['Inje', '인제대학교', '인제대']],
  ['Jeju National University', ['Jeju', '제주대학교', '제주대']],
  ['Korea Maritime and Ocean University', ['KMOU', '한국해양대학교', '한국해양대']],
  ['Keimyung University', ['Keimyung', '계명대학교', '계명대']],
  ['Konkuk University', ['Konkuk', '건국대학교', '건국대']],
  ['Kumoh National Institute of Technology', ['Kumoh', '금오공과대학교', '금오공대']],
  ['Mokwon University', ['Mokwon', '목원대학교', '목원대']],
  ['Myongji University', ['Myongji', '명지대학교', '명지대']],
  ['Pukyong National University', ['Pukyong', '부경대학교', '부경대']],
  ['Seokyeong University', ['Seokyeong', '서경대학교', '서경대']],
  ['Wonkwang University', ['Wonkwang', '원광대학교', '원광대']],
  ['Yeungnam University', ['Yeungnam', '영남대학교', '영남대']],
  ['Catholic University of Korea', ['Catholic', '가톨릭대학교', '가톨릭대']],
  ['Chosun University', ['Chosun', '조선대학교', '조선대']],
  ['Daegu University', ['Daegu', '대구대학교', '대구대']],
  ['Daejeon University', ['Daejeon', '대전대학교', '대전대']],
  ['Dong-Eui University', ['Dong-Eui', '동의대학교', '동의대']],
  ['Handong Global University', ['Handong', '한동대학교', '한동대']],
  ['Hankuk University of Foreign Studies', ['Hankuk', '한국외국어대학교', '한국외대']],
  ['Kongju National University', ['Kongju', '공주대학교', '공주대']],
  ['Kosin University', ['Kosin', '고신대학교', '고신대']],
  ['Kwangwoon University', ['Kwangwoon', '광운대학교', '광운대']],
  ['Kyonggi University', ['Kyonggi', '경기대학교', '경기대']],
  ['Kyungsung University', ['Kyungsung', '경성대학교', '경성대']],
  ['Pai Chai University', ['Pai Chai', '배재대학교', '배재대']],
  ['Seoul National University of Science and Technology', ['SNUST', 'SEOULTECH', '서울과학기술대학교', '서울과기대']],
  ['Sejong University', ['Sejong', '세종대학교', '세종대']],
  ["Seoul Women's University", ["Seoul Women's", '서울여자대학교', '서울여대']],
  ["Sookmyung Women's University", ['Sookmyung', '숙명여자대학교', '숙명여대']],
  ['Soonchunhyang University', ['Soonchunhyang', '순천향대학교', '순천향대']],
  ['Soongsil University', ['Soongsil', '숭실대학교', '숭실대']],
  ['Sunchon National University', ['Sunchon', '순천대학교', '순천대']],
  ['University of Suwon', ['Suwon', '수원대학교', '수원대']],
  ['University of Seoul', ['UOS', '서울시립대학교', '서울시립대']],
  ['Daegu Catholic University', ['Daegu Catholic', '대구가톨릭대학교', '대구가톨릭대']],
  ['Sangmyung University', ['Sangmyung', '상명대학교', '상명대']],
  ['Hongik University', ['Hongik', '홍익대학교', '홍익대']],
  ['Kyungnam University', ['Kyungnam', '경남대학교', '경남대']],
  ['Seowon University', ['Seowon', '서원대학교', '서원대']],
  ['Andong National University', ['Andong', '안동대학교', '안동대']],
  ['Jungwon University', ['Jungwon', '중원대학교', '중원대']],
];
const displayKey = (value: string) => key(value).replace(/[–—−]/g, '-');
const displayLookup = new Map<string, string>();
const searchAliases = new Map<string, Set<string>>();
for (const [fullName, variants] of displayAliases) {
  const names = searchAliases.get(fullName) || new Set<string>();
  for (const name of [fullName, ...variants]) {
    displayLookup.set(displayKey(name), fullName);
    names.add(name);
  }
  searchAliases.set(fullName, names);
}

/** Full English label only; never use this to decide identity or count membership. */
export function institutionDisplayName(value: string | null | undefined): string {
  if (!value?.trim()) return '정보 없음';
  return displayLookup.get(displayKey(value)) || value.trim();
}

/** Retain Korean names and abbreviations as search terms after relabelling. */
export function institutionSearchText(value: string | null | undefined): string {
  if (!value?.trim()) return '';
  const fullName = institutionDisplayName(value);
  return [...(searchAliases.get(fullName) || [fullName]), value].join(' ');
}
