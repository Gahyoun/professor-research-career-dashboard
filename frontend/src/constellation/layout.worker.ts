import { buildHypergraph, layoutHypergraph } from './hypergraph';
import { buildTrajectoryHypergraph } from './trajectoryGraph';
import { layoutLifetimeHypergraph } from './lifetimeLayout';

self.onmessage = ({ data }) => {
  try {
    const graph = data.selectedId ? buildTrajectoryHypergraph(data.records, data.selectedId, data.options, data.preparedLifetime) : buildHypergraph(data.records, data.options);
    const layout = data.selectedId ? layoutLifetimeHypergraph(graph, data.layout) : layoutHypergraph(graph, data.layout);
    self.postMessage({ type: 'result', result: { graph, layout } });
  } catch {
    self.postMessage({ type: 'error' });
  }
};
