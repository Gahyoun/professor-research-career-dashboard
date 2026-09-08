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
