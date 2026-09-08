import type { LifetimeResult, LifetimeStage } from './lifetime';

export type CareerStageSummary = { intervalCount: number; groupCount: number; peerCount: number };
export type CareerSummary = {
  id: string; eligibleStages: number; groupCount: number; peerCount: number;
  stages: Record<LifetimeStage, CareerStageSummary>;
};

/** One row per researcher, including isolated researchers and those with missing evidence. */
export function summarizeCareer(result: LifetimeResult): CareerSummary {
  const stages: CareerSummary['stages'] = {
    doctoral: { intervalCount: 0, groupCount: 0, peerCount: 0 },
    postdoc: { intervalCount: 0, groupCount: 0, peerCount: 0 },
    first_faculty: { intervalCount: 0, groupCount: 0, peerCount: 0 },
    current: { intervalCount: 0, groupCount: 0, peerCount: 0 },
  };
  for (const stage of result.stages) stages[stage.stage] = {
    intervalCount: stage.intervals.length, groupCount: stage.groups.length,
    peerCount: new Set(stage.groups.flatMap(group => group.members).filter(id => id !== result.selectedId)).size,
  };
  return { id: result.selectedId, eligibleStages: result.coverage.eligibleStages,
    groupCount: result.coverage.groupCount, peerCount: result.coverage.peerCount, stages };
}
