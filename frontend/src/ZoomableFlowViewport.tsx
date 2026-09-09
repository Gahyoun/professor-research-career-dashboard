import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent, PointerEvent, ReactNode } from 'react';
import { fitFlowCamera, flowZoomBounds, panFlowCamera, revealFlowRect, zoomFlowCamera } from './flowCamera';
import type { FlowCamera, FlowSize } from './flowCamera';

type Point = { x: number; y: number };
type Gesture = { camera: FlowCamera; center: Point; distance: number; moved: boolean };
type Props = { width: number; height: number; resetToken: unknown; onGestureStart: () => void; children: ReactNode };
const centerOf = (points: Point[]): Point => points.length > 1
  ? { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 } : points[0];
const distanceOf = (points: Point[]) => points.length > 1 ? Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y) : 0;

/** Only the viewport transform changes while navigating; the flow graph stays intact. */
export default function ZoomableFlowViewport({ width, height, resetToken, onGestureStart, children }: Props) {
  const instructionsId = useId();
  const viewport = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<FlowSize>({ width: 0, height: 0 });
  const scene = useMemo(() => ({ width, height }), [width, height]);
  const bounds = useMemo(() => flowZoomBounds(size, scene), [size, scene]);
  const [camera, setCamera] = useState<FlowCamera>({ x: 0, y: 0, zoom: 1 });
  const cameraRef = useRef(camera);
  const [dragging, setDragging] = useState(false);
  const pointers = useRef(new Map<number, Point>());
  const gesture = useRef<Gesture | null>(null);
  const suppressClick = useRef(false);
  const previousView = useRef<{ size: FlowSize; scene: FlowSize; token: unknown } | null>(null);
  const commit = useCallback((next: FlowCamera) => { cameraRef.current = next; setCamera(next); }, []);

  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setSize(previous => {
      const next = { width: element.clientWidth, height: element.clientHeight };
      return next.width === previous.width && next.height === previous.height ? previous : next;
    }));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!size.width || !size.height) return;
    const previous = previousView.current;
    if (previous && previous.token === resetToken && previous.scene.width === width && previous.scene.height === height) {
      // Keep the same scene point at the viewport center during a panel resize.
      const centered = panFlowCamera(cameraRef.current, (size.width - previous.size.width) / 2, (size.height - previous.size.height) / 2);
      commit(zoomFlowCamera(centered, centered.zoom, { x: size.width / 2, y: size.height / 2 }, bounds));
    } else {
      commit(fitFlowCamera(size, scene, 'width'));
      pointers.current.clear(); gesture.current = null; suppressClick.current = false; setDragging(false);
    }
    previousView.current = { size, scene, token: resetToken };
  }, [size, scene, width, height, resetToken, bounds, commit]);

  const localPoint = (clientX: number, clientY: number): Point => {
    const rect = viewport.current!.getBoundingClientRect();
    return { x: clientX - rect.left - viewport.current!.clientLeft, y: clientY - rect.top - viewport.current!.clientTop };
  };
  function zoomBy(factor: number) {
    onGestureStart();
    commit(zoomFlowCamera(cameraRef.current, cameraRef.current.zoom * factor, { x: size.width / 2, y: size.height / 2 }, bounds));
  }
  function fit(mode: 'width' | 'all') { onGestureStart(); commit(fitFlowCamera(size, scene, mode)); }

  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      onGestureStart();
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? size.height : 1;
      if (event.ctrlKey || event.metaKey) {
        const rect = element.getBoundingClientRect();
        const factor = Math.exp(-Math.max(-300, Math.min(300, event.deltaY * unit)) * .003);
        commit(zoomFlowCamera(cameraRef.current, cameraRef.current.zoom * factor, { x: event.clientX - rect.left - element.clientLeft, y: event.clientY - rect.top - element.clientTop }, bounds));
      } else {
        const dx = event.shiftKey && !event.deltaX ? event.deltaY : event.deltaX;
        const dy = event.shiftKey && !event.deltaX ? 0 : event.deltaY;
        commit(panFlowCamera(cameraRef.current, -dx * unit, -dy * unit));
      }
    };
    element.addEventListener('wheel', wheel, { passive: false });
    return () => element.removeEventListener('wheel', wheel);
  }, [size.height, bounds, onGestureStart, commit]);

  function startPointer(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || pointers.current.size >= 2) return;
    if (!pointers.current.size) suppressClick.current = false;
    pointers.current.set(event.pointerId, localPoint(event.clientX, event.clientY));
    const points = [...pointers.current.values()];
    gesture.current = { camera: cameraRef.current, center: centerOf(points), distance: distanceOf(points), moved: pointers.current.size > 1 || suppressClick.current };
    if (points.length > 1) {
      suppressClick.current = true; setDragging(true); onGestureStart();
      for (const id of pointers.current.keys()) event.currentTarget.setPointerCapture(id);
    }
  }
  function movePointer(event: PointerEvent<HTMLDivElement>) {
    if (!pointers.current.has(event.pointerId) || !gesture.current) return;
    pointers.current.set(event.pointerId, localPoint(event.clientX, event.clientY));
    const points = [...pointers.current.values()], center = centerOf(points), start = gesture.current;
    const dx = center.x - start.center.x, dy = center.y - start.center.y;
    if (!start.moved && Math.hypot(dx, dy) < 5) return;
    start.moved = true; suppressClick.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true); onGestureStart();
    const zoomed = points.length > 1 && start.distance > 0
      ? zoomFlowCamera(start.camera, start.camera.zoom * distanceOf(points) / start.distance, start.center, bounds) : start.camera;
    commit(panFlowCamera(zoomed, dx, dy));
  }
  function endPointer(event: PointerEvent<HTMLDivElement>) {
    if (!pointers.current.delete(event.pointerId)) return;
    if (event.type === 'pointercancel') suppressClick.current = true;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    const points = [...pointers.current.values()];
    gesture.current = points.length ? { camera: cameraRef.current, center: centerOf(points), distance: distanceOf(points), moved: suppressClick.current } : null;
    if (!points.length) setDragging(false);
  }
  function handleKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const shifts: Record<string, Point> = { ArrowLeft: { x: 60, y: 0 }, ArrowRight: { x: -60, y: 0 }, ArrowUp: { x: 0, y: 60 }, ArrowDown: { x: 0, y: -60 } };
    if (shifts[event.key]) { event.preventDefault(); onGestureStart(); commit(panFlowCamera(cameraRef.current, shifts[event.key].x, shifts[event.key].y)); }
    else if (['+', '='].includes(event.key)) { event.preventDefault(); zoomBy(1.25); }
    else if (['-', '_'].includes(event.key)) { event.preventDefault(); zoomBy(.8); }
    else if (event.key === '0') { event.preventDefault(); fit('all'); }
    else if (event.key === 'Home') { event.preventDefault(); fit('width'); }
  }

  return <div className="sk-flow-viewer">
    <div className="sk-view-toolbar" role="group" aria-label="흐름 도표 보기 조절">
      <div className="sk-zoom-buttons"><button className="sk-button" onClick={() => zoomBy(.8)} disabled={camera.zoom <= bounds.min * 1.001} aria-label="흐름 도표 축소">−</button><output aria-live="polite" aria-label="흐름 도표 배율">{camera.zoom * 100 < 10 ? (camera.zoom * 100).toFixed(1) : Math.round(camera.zoom * 100)}%</output><button className="sk-button" onClick={() => zoomBy(1.25)} disabled={camera.zoom >= bounds.max * .999} aria-label="흐름 도표 확대">+</button></div>
      <div className="sk-fit-buttons"><button className="sk-button" onClick={() => fit('width')}>가로 맞춤</button><button className="sk-button" onClick={() => fit('all')}>전체 보기</button><button className="sk-button" onClick={() => { onGestureStart(); commit(zoomFlowCamera(cameraRef.current, 1, { x: size.width / 2, y: size.height / 2 }, bounds)); }}>100%</button></div>
    </div>
    <p className="sk-canvas-hint" id={instructionsId}>드래그·휠로 이동 · Ctrl/⌘ + 휠 또는 두 손가락 핀치로 확대·축소. 키보드: 방향키 이동, +/− 확대·축소, 0 전체 보기.</p>
    <div ref={viewport} className={`sk-flow-canvas${dragging ? ' is-dragging' : ''}`} tabIndex={0} role="region" aria-label="학력 흐름 확대·축소 캔버스" aria-describedby={instructionsId}
      onPointerDown={startPointer} onPointerMove={movePointer} onPointerUp={endPointer} onPointerCancel={endPointer}
      onLostPointerCapture={event => { if (event.target === event.currentTarget) endPointer(event); }}
      onPointerLeave={event => { if (!event.currentTarget.hasPointerCapture(event.pointerId)) endPointer(event); }}
      onClickCapture={event => { if (event.detail > 0 && suppressClick.current) { event.preventDefault(); event.stopPropagation(); suppressClick.current = false; } }}
      onKeyDown={handleKey}
      onFocusCapture={event => {
        if (event.target === event.currentTarget || !(event.target instanceof SVGElement) || !event.target.matches(':focus-visible')) return;
        const rect = (event.target.querySelector('.sk-label-bg') ?? event.target).getBoundingClientRect(), view = event.currentTarget.getBoundingClientRect();
        commit(revealFlowRect(cameraRef.current, { x: rect.left - view.left - event.currentTarget.clientLeft, y: rect.top - view.top - event.currentTarget.clientTop, width: rect.width, height: rect.height }, size, bounds));
      }}>
      <div className="sk-flow-world" style={{ width, height, transform: `translate(${camera.x}px, ${camera.y}px) scale(${camera.zoom})` }}>{children}</div>
    </div>
  </div>;
}
