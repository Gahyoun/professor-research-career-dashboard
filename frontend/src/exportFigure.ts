/** Vector export of an on-screen SVG figure (Sankey, topic alluvial).
 *  The clone carries computed styles inline, so it renders the same outside the page's CSS.
 *  PDF goes through the browser's print engine — text stays text and Korean glyphs use the
 *  system fonts — so no PDF/font library ships with the app. Hover <title>/<desc> text is
 *  dropped from the copy. */
/** ``columns``: stage headings drawn above the figure at x positions in SVG units (HTML headings are not part of the SVG). */
export type FigureColumn = { x: number; label: string; anchor?: 'start' | 'middle' | 'end' };
export type FigureMeta = { title: string; subtitle?: string; legend?: { label: string; color: string; strong?: boolean }[]; note?: string; filename: string; columns?: FigureColumn[] };

const STYLE_PROPS = [
  'fill', 'fill-opacity', 'stroke', 'stroke-width', 'stroke-opacity', 'stroke-dasharray', 'stroke-linejoin', 'stroke-linecap',
  'opacity', 'paint-order', 'font-family', 'font-size', 'font-weight', 'font-variant-numeric', 'letter-spacing',
  'text-anchor', 'dominant-baseline', 'visibility', 'display',
] as const;

/** Detached copy of ``svg`` at its viewBox size with inline styles and without hover text. */
export function standaloneSvg(svg: SVGSVGElement, columns: FigureColumn[] = []): SVGSVGElement {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const source = [svg, ...svg.querySelectorAll('*')], target = [clone, ...clone.querySelectorAll('*')];
  source.forEach((node, i) => {
    const computed = getComputedStyle(node), out = target[i] as SVGElement;
    out.removeAttribute('class');
    out.style.cssText = STYLE_PROPS.map(prop => `${prop}:${computed.getPropertyValue(prop)}`).join(';');
  });
  clone.querySelectorAll('title, desc').forEach(node => node.remove());
  clone.querySelectorAll('[role], [tabindex], [aria-label], [aria-labelledby], [aria-pressed]').forEach(node => {
    for (const attr of ['role', 'tabindex', 'aria-label', 'aria-labelledby', 'aria-pressed']) node.removeAttribute(attr);
  });
  const box = svg.viewBox.baseVal;
  const width = box?.width || svg.getBoundingClientRect().width, height = box?.height || svg.getBoundingClientRect().height;
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('width', String(width));
  clone.setAttribute('height', String(height));
  clone.style.maxWidth = 'none';
  if (!columns.length) return clone;
  const ns = 'http://www.w3.org/2000/svg', top = 40;
  const outer = document.createElementNS(ns, 'svg');
  outer.setAttribute('xmlns', ns);
  outer.setAttribute('width', String(width));
  outer.setAttribute('height', String(height + top));
  outer.setAttribute('viewBox', `0 0 ${width} ${height + top}`);
  const font = getComputedStyle(svg).fontFamily;
  for (const column of columns) {
    const text = document.createElementNS(ns, 'text');
    Object.entries({ x: column.x, y: 22, 'text-anchor': column.anchor ?? 'middle' }).forEach(([k, v]) => text.setAttribute(k, String(v)));
    text.style.cssText = `font-family:${font};font-size:17px;font-weight:700;fill:#1e2124`;
    text.textContent = column.label;
    outer.append(text);
  }
  clone.setAttribute('y', String(top));
  outer.append(clone);
  return outer;
}

const escape = (text: string) => text.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

export function downloadSvg(svg: SVGSVGElement, filename: string, columns: FigureColumn[] = []): void {
  const text = '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(standaloneSvg(svg, columns));
  const url = URL.createObjectURL(new Blob([text], { type: 'image/svg+xml;charset=utf-8' }));
  const link = Object.assign(document.createElement('a'), { href: url, download: `${filename}.svg` });
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Opens the print dialog on a one-page document sized to the figure; choose "PDF로 저장". */
export function printSvgAsPdf(svg: SVGSVGElement, meta: FigureMeta): void {
  const figure = standaloneSvg(svg, meta.columns);
  const width = Number(figure.getAttribute('width')), height = Number(figure.getAttribute('height'));
  const pad = 48, header = 64 + (meta.subtitle ? 24 : 0) + (meta.legend?.length ? 32 : 0), footer = meta.note ? 44 : 20;
  const pageW = width + 2 * pad, pageH = height + header + footer + 2 * pad;
  const font = getComputedStyle(document.body).fontFamily;
  const legend = meta.legend?.length ? `<ul>${meta.legend.map(item => `<li><i style="background:${escape(item.color)};${item.strong ? 'height:6px;width:22px' : ''}"></i>${escape(item.label)}</li>`).join('')}</ul>` : '';
  const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>${escape(meta.filename)}</title><style>
    @page { size: ${pageW}px ${pageH}px; margin: 0; }
    * { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    html, body { margin: 0; background: #fff; color: #1e2124; font-family: ${font}; }
    main { width: ${pageW}px; height: ${pageH}px; padding: ${pad}px; overflow: hidden; }
    h1 { font-size: 26px; margin: 0 0 6px; font-weight: 700; letter-spacing: -.01em; }
    p { margin: 0; font-size: 15px; color: #464c53; }
    ul { list-style: none; display: flex; flex-wrap: wrap; gap: 6px 20px; margin: 14px 0 0; padding: 0; font-size: 14px; color: #464c53; }
    li { display: flex; align-items: center; gap: 7px; } li i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; }
    figure { margin: 20px 0 0; } footer { margin-top: 14px; font-size: 12px; color: #6d7882; }
  </style></head><body><main><h1>${escape(meta.title)}</h1>${meta.subtitle ? `<p>${escape(meta.subtitle)}</p>` : ''}${legend}<figure>${new XMLSerializer().serializeToString(figure)}</figure>${meta.note ? `<footer>${escape(meta.note)}</footer>` : ''}</main></body></html>`;

  const frame = document.createElement('iframe');
  frame.setAttribute('aria-hidden', 'true');
  frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden';
  document.body.append(frame);
  const doc = frame.contentDocument!;
  doc.open(); doc.write(html); doc.close();
  const previousTitle = document.title;
  // Safari and Chrome take the PDF file name from the top document's title.
  document.title = meta.filename;
  const cleanup = () => { document.title = previousTitle; frame.remove(); };
  frame.contentWindow!.addEventListener('afterprint', () => setTimeout(cleanup, 0), { once: true });
  setTimeout(() => {
    frame.contentWindow!.focus();
    frame.contentWindow!.print();
    setTimeout(() => { if (frame.isConnected) cleanup(); }, 60_000);
  }, 120);
}

export const figureDate = () => new Date().toISOString().slice(0, 10);
