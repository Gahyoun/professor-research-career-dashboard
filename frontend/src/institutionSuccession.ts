import type { Dashboard } from './types';

/** Explicit legal university successions. Dates are projected to annual bins. */
export const INSTITUTION_SUCCESSIONS = [
  {
    id: 'gnu-2021', effectiveDate: '2021-03-01', effectiveYear: 2021,
    label: '경상국립대학교',
    seriesAnchorLabel: 'Gyeongsang National University',
    predecessorNames: ['경남과학기술대학교', '경남과학기술대', '경남과기대', 'Gyeongnam National University of Science and Technology'],
    source: 'https://www.gnu.ac.kr/archives/cm/cntnts/cntntsView.do?cntntsId=3998&mi=7470',
    names: ['경상국립대학교', '경상국립대', '경상대학교', '경상대', 'Gyeongsang National University',
      '경남과학기술대학교', '경남과학기술대', '경남과기대', 'Gyeongnam National University of Science and Technology'],
  },
  {
    id: 'kangwon-2026', effectiveDate: '2026-03-01', effectiveYear: 2026,
    label: '강원대학교 (통합)',
    seriesAnchorLabel: 'Kangwon National University',
    predecessorNames: ['Gangneung-Wonju National University', '국립강릉원주대학교', '강릉원주대학교', '강릉원주대'],
    source: 'https://home.kangwon.ac.kr/',
    names: ['강원대학교 (통합)', '통합강원대', '강원대학교', '강원대', 'Kangwon National University',
      'Gangneung-Wonju National University', '국립강릉원주대학교', '강릉원주대학교', '강릉원주대'],
  },
] as const;
const key = (value: string) => value.normalize('NFKC').trim().toLowerCase()
  .replace(/[–—−]/g, '-').replace(/\s+/g, ' ');
function succession(value: string | null | undefined) {
  return value ? INSTITUTION_SUCCESSIONS.find(rule => rule.names.some(name => key(name) === key(value))) : undefined;
}

/** For a current roster or a specified annual snapshot; never rewrite degree history. */
export function currentInstitutionName(value: string | null | undefined, year: number): string | null {
  const rule = succession(value);
  return rule && Number.isInteger(year) && year >= rule.effectiveYear ? rule.label : value ?? null;
}

/** A transition before the legal merger remains a possible institutional move. */
export function isInstitutionSuccession(from: string, to: string, transitionYear: number): boolean {
  const a = succession(from), b = succession(to);
  return !!a && a.id === b?.id && Number.isInteger(transitionYear) && transitionYear >= a.effectiveYear;
}

/** Apply only after supplemental metadata has been validated against the raw release. */
export function applyInstitutionSuccessions(dashboard: Dashboard): Dashboard {
  const year = dashboard.meta.release_year;
  const professors = dashboard.professors.map(person => {
    const faculty = person.career.map((row, index) => ({ row, index }))
      .filter(({ row }) => row.stage === 'faculty' && Number.isInteger(row.start_year))
      .sort((a, b) => a.row.start_year! - b.row.start_year! || a.index - b.index);
    const continuing = new Set<number>();
    for (let i = 1; i < faculty.length; i++) {
      const previous = faculty[i - 1].row, current = faculty[i].row;
      if (key(previous.institution) !== key(current.institution) &&
          isInstitutionSuccession(previous.institution, current.institution, current.start_year!)) continuing.add(faculty[i].index);
    }
    return { ...person,
      current_institution: currentInstitutionName(person.current_institution, year),
      current_position: person.current_position ? { ...person.current_position,
        institution: currentInstitutionName(person.current_position.institution, year)!,
        institution_canonical: currentInstitutionName(person.current_position.institution_canonical || person.current_position.institution, year)! } : undefined,
      career: person.career.map((row, index) => {
        if (!continuing.has(index)) return row;
        const note = '대학 통합에 따른 기관 승계 · 이직 제외';
        return { ...row, is_institution_successor: true,
          evidence_basis: row.evidence_basis?.includes(note) ? row.evidence_basis : [row.evidence_basis, note].filter(Boolean).join('; ') };
      }),
    };
  });
  return { ...dashboard, professors, filters: { ...dashboard.filters,
    current_institutions: [...new Set(professors.map(p => p.current_institution).filter((x): x is string => !!x))].sort(),
  } };
}
