import { useEffect, useState } from 'react';
import { normalizeResearchAreas, type ResearchAreas } from './researchAreas';

let cache: Promise<ResearchAreas | null> | null = null;

/** Fetched once per page load; null while loading or when the optional file is absent. */
export function loadResearchAreas(): Promise<ResearchAreas | null> {
  cache ??= fetch(`${import.meta.env.BASE_URL}data/research_areas.json`)
    .then(response => response.ok ? response.json() : null).then(normalizeResearchAreas).catch(() => null);
  return cache;
}

export function useResearchAreas(): ResearchAreas | null {
  const [areas, setAreas] = useState<ResearchAreas | null>(null);
  useEffect(() => {
    let live = true;
    loadResearchAreas().then(value => { if (live) setAreas(value); });
    return () => { live = false; };
  }, []);
  return areas;
}
