/** View transforms only: counts, node sizes and person-to-width scales stay intact. */
export type FlowCamera = { x: number; y: number; zoom: number };
export type FlowSize = { width: number; height: number };
export type FlowZoomBounds = { min: number; max: number };
const PADDING = 24;
const dimension = (value: number) => Number.isFinite(value) && value > 0 ? Math.max(1, value) : 1;
const finite = (value: number, fallback = 0) => Number.isFinite(value) ? value : fallback;
const positive = (value: number, fallback = 1) => Number.isFinite(value) && value > 0 ? value : fallback;
function sizes(viewport: FlowSize, scene: FlowSize) {
  const width = dimension(viewport.width), height = dimension(viewport.height);
  return { width, height, sceneWidth: dimension(scene.width), sceneHeight: dimension(scene.height),
    availableWidth: Math.max(1, width - 2 * PADDING), availableHeight: Math.max(1, height - 2 * PADDING) };
}

/** The minimum always permits the whole scene, including very tall flow diagrams. */
export function flowZoomBounds(viewport: FlowSize, scene: FlowSize): FlowZoomBounds {
  const size = sizes(viewport, scene);
  return { min: Math.min(1, size.availableWidth / size.sceneWidth, size.availableHeight / size.sceneHeight), max: 4 };
}

/** Width mode starts at the top; all mode centres the entire scene on both axes. */
export function fitFlowCamera(viewport: FlowSize, scene: FlowSize, mode: 'width' | 'all' = 'width'): FlowCamera {
  const size = sizes(viewport, scene);
  const zoom = mode === 'all' ? flowZoomBounds(viewport, scene).min : Math.min(1, size.availableWidth / size.sceneWidth);
  return { x: (size.width - size.sceneWidth * zoom) / 2,
    y: mode === 'all' ? (size.height - size.sceneHeight * zoom) / 2 : (size.height - size.availableHeight) / 2,
    zoom };
}

/** anchor is in viewport pixels; the same scene point remains beneath it. */
export function zoomFlowCamera(camera: FlowCamera, nextZoom: number, anchor: { x: number; y: number }, bounds: FlowZoomBounds): FlowCamera {
  const previousZoom = positive(camera.zoom), max = positive(bounds.max, 4), min = Math.min(max, positive(bounds.min, Math.min(1, max)));
  const zoom = Math.min(max, Math.max(min, Number.isNaN(nextZoom) ? previousZoom : nextZoom));
  const x = finite(camera.x), y = finite(camera.y), ax = finite(anchor.x), ay = finite(anchor.y);
  const ratio = zoom / previousZoom;
  return { x: finite(ax - (ax - x) * ratio, x), y: finite(ay - (ay - y) * ratio, y), zoom };
}

export function panFlowCamera(camera: FlowCamera, dx: number, dy: number): FlowCamera {
  const x = finite(camera.x), y = finite(camera.y);
  return { x: finite(x + finite(dx), x), y: finite(y + finite(dy), y), zoom: positive(camera.zoom) };
}

/** Reveal a rendered viewport-local label, shrinking only when its size requires it. */
export function revealFlowRect(camera: FlowCamera, rect: { x: number; y: number; width: number; height: number },
  viewport: FlowSize, bounds: FlowZoomBounds): FlowCamera {
  const width = dimension(viewport.width), height = dimension(viewport.height);
  const availableWidth = Math.max(1, width - 32), availableHeight = Math.max(1, height - 32);
  const padX = (width - availableWidth) / 2, padY = (height - availableHeight) / 2;
  const x = finite(rect.x), y = finite(rect.y), rectWidth = Math.max(0, finite(rect.width)), rectHeight = Math.max(0, finite(rect.height));
  if (x >= padX && y >= padY && x + rectWidth <= width - padX && y + rectHeight <= height - padY) return camera;
  const reduction = Math.min(1, rectWidth > 0 ? availableWidth / rectWidth : 1, rectHeight > 0 ? availableHeight / rectHeight : 1);
  const anchor = { x: width / 2, y: height / 2 };
  const zoomed = reduction < 1 ? zoomFlowCamera(camera, positive(camera.zoom) * reduction, anchor, bounds) : camera;
  const scale = positive(zoomed.zoom) / positive(camera.zoom);
  const nextX = anchor.x + (x - anchor.x) * scale, nextY = anchor.y + (y - anchor.y) * scale;
  const nextWidth = rectWidth * scale, nextHeight = rectHeight * scale;
  const shift = (start: number, length: number, available: number, padding: number) => {
    // If the minimum zoom prevents full fitting, centre the oversized dimension
    // for maximal visibility without violating the caller's zoom bounds.
    if (length > available + 1e-9) return padding + (available - length) / 2 - start;
    if (start < padding) return padding - start;
    if (start + length > padding + available) return padding + available - start - length;
    return 0;
  };
  const dx = shift(nextX, nextWidth, availableWidth, padX), dy = shift(nextY, nextHeight, availableHeight, padY);
  return dx || dy ? panFlowCamera(zoomed, dx, dy) : zoomed;
}
