import { buildHypergraph, layoutHypergraph } from './hypergraph';
import { buildTrajectoryHypergraph } from './trajectoryGraph';

self.onmessage = ({ data }) => {
  try {
    const graph = data.selectedId ? buildTrajectoryHypergraph(data.records, data.selectedId, data.options) : buildHypergraph(data.records, data.options);
    const layout = layoutHypergraph(graph, data.layout);
    self.postMessage({ type: 'result', result: { graph, layout } });
  } catch {
    self.postMessage({ type: 'error' });
  }
};
