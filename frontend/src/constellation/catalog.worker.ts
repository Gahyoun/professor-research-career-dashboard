import { createLifetimeIndex } from './lifetime';
import { summarizeCareer, type CareerSummary } from './careerCatalog';

self.onmessage = async ({ data }) => {
  try {
    const index = createLifetimeIndex(data.records, data.options);
    const summaries: Record<string, CareerSummary> = {};
    let batch: Record<string, CareerSummary> = {};
    self.postMessage({ type: 'progress', progress: 0 });
    for (let i = 0; i < index.ids.length; i++) {
      const id = index.ids[i];
      summaries[id] = summarizeCareer(index.get(id));
      batch[id] = summaries[id];
      if ((i + 1) % 250 === 0) {
        self.postMessage({ type: 'progress', progress: (i + 1) / index.ids.length, summaries: batch });
        batch = {};
        await new Promise(resolve => setTimeout(resolve, 0));
      }
    }
    self.postMessage({ type: 'result', summaries });
  } catch {
    self.postMessage({ type: 'error' });
  }
};
