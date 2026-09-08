import type { LifetimeStage } from './constellation/lifetime';

/** Edge-stage colors are independent of the subject colors used for researcher dots. */
export const lifetimeStageColors: Record<LifetimeStage, string> = {
  doctoral: '#a95c00', postdoc: '#008575', first_faculty: '#7652ae', current: '#256ef4',
};
export const lifetimeStageLabels: Record<LifetimeStage, string> = {
  doctoral: '박사과정', postdoc: '포닥', first_faculty: '첫 조교수', current: '현직',
};

export function lifetimePeriod(start: number, end: number): string {
  return start === end ? `${start}년` : `${start}–${end}년`;
}
