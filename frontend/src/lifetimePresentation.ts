import type { LifetimeStage } from './constellation/lifetime';
import { institutionDisplayName } from './schoolIdentity';

/** Edge-stage colors are independent of the subject colors used for researcher dots. */
export const lifetimeStageColors: Record<LifetimeStage, string> = {
  doctoral: '#a95c00', postdoc: '#008575', first_faculty: '#7652ae', current: '#256ef4',
};
export const lifetimeStageLabels: Record<LifetimeStage, string> = {
  doctoral: '박사과정', postdoc: '포닥', first_faculty: '첫 조교수', current: '현직',
};
export const careerSubjectLabels: Record<string, string> = {
  mathematics: '수학', physics: '물리', chemistry: '화학', biology: '생물',
};

export function lifetimeUnitLabel(unit: {
  institution: string; subject?: string; department?: string;
  matchingBasis?: 'institution_subject' | 'institution_department_subject';
}): string {
  const parts = [institutionDisplayName(unit.institution), `명부 분야: ${careerSubjectLabels[unit.subject || ''] || '미상'}`];
  if (unit.matchingBasis === 'institution_department_subject' && unit.department) parts.push(`과거 학과: ${unit.department}`);
  return parts.join(' · ');
}

export function lifetimePeriod(start: number, end: number): string {
  return start === end ? `${start}년` : `${start}–${end}년`;
}
