import test from 'node:test';
import assert from 'node:assert/strict';
import { flowZoomBounds, fitFlowCamera, zoomFlowCamera, panFlowCamera, revealFlowRect } from '../work/test-dist/flowCamera.js';
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} differs from ${b}`);
const finiteCamera = camera => { assert.ok(Object.values(camera).every(Number.isFinite)); assert.ok(camera.zoom > 0); };

test('zoom keeps the scene point beneath a viewport anchor fixed, including after prior panning', () => {
  const original = { x: -172, y: -1090, zoom: .35 }, anchor = { x: 443, y: 232 };
  const before = { x: (anchor.x - original.x) / original.zoom, y: (anchor.y - original.y) / original.zoom };
  for (const next of [.03, .6, 2.5]) {
    const changed = zoomFlowCamera(original, next, anchor, { min: .02, max: 4 });
    close((anchor.x - changed.x) / changed.zoom, before.x);
    close((anchor.y - changed.y) / changed.zoom, before.y);
  }
  assert.deepEqual(original, { x: -172, y: -1090, zoom: .35 });
});

test('zoom clamps at both bounds, while unchanged clamped zoom preserves camera position', () => {
  const anchor = { x: 20, y: 90 }, camera = { x: -10, y: 24, zoom: .5 }, bounds = { min: .025, max: 4 };
  assert.equal(zoomFlowCamera(camera, -Infinity, anchor, bounds).zoom, .025);
  assert.equal(zoomFlowCamera(camera, Infinity, anchor, bounds).zoom, 4);
  assert.deepEqual(zoomFlowCamera(camera, NaN, anchor, bounds), camera);
  const minimum = zoomFlowCamera(camera, 0, anchor, bounds);
  assert.deepEqual(zoomFlowCamera(minimum, -100, anchor, bounds), minimum);
});

test('a 20,000-pixel scene fits fully at minimum zoom and width-fit keeps its top visible', () => {
  const viewport = { width: 1100, height: 700 }, scene = { width: 1540, height: 20000 };
  const all = fitFlowCamera(viewport, scene, 'all'), width = fitFlowCamera(viewport, scene);
  assert.equal(all.zoom, flowZoomBounds(viewport, scene).min);
  assert.ok(all.x >= 24 && all.y >= 24);
  assert.ok(all.x + scene.width * all.zoom <= viewport.width - 24 + 1e-9);
  assert.ok(all.y + scene.height * all.zoom <= viewport.height - 24 + 1e-9);
  close(width.x, 24); close(width.y, 24); close(width.zoom, (viewport.width - 48) / scene.width);
  assert.ok(all.zoom < width.zoom);
  finiteCamera(all); finiteCamera(width);
});

test('narrow viewports adapt padding and still fit the whole scene without scaling above one', () => {
  for (const viewport of [{ width: 320, height: 480 }, { width: 20, height: 30 }, { width: 1, height: 1 }]) {
    const scene = { width: 1540, height: 20000 }, camera = fitFlowCamera(viewport, scene, 'all');
    assert.ok(camera.x >= 0 && camera.y >= 0);
    assert.ok(camera.x + scene.width * camera.zoom <= viewport.width + 1e-9);
    assert.ok(camera.y + scene.height * camera.zoom <= viewport.height + 1e-9);
    assert.ok(camera.zoom <= 1); finiteCamera(camera);
  }
  assert.equal(fitFlowCamera({ width: 1000, height: 1000 }, { width: 100, height: 100 }, 'all').zoom, 1);
  assert.equal(fitFlowCamera({ width: 1000, height: 1000 }, { width: 100, height: 100 }).zoom, 1);
});

test('panning and its inverse preserve scale and leave input objects unchanged', () => {
  const camera = { x: 10, y: 24, zoom: .15 };
  const moved = panFlowCamera(camera, -241, 193);
  assert.deepEqual(moved, { x: -231, y: 217, zoom: .15 });
  assert.deepEqual(panFlowCamera(moved, 241, -193), camera);
  assert.deepEqual(camera, { x: 10, y: 24, zoom: .15 });
});

test('empty or malformed dimensions and camera events always produce finite transforms', () => {
  for (const value of [0, -2, NaN, Infinity, -Infinity]) {
    const viewport = { width: value, height: value }, scene = { width: value, height: value };
    const bounds = flowZoomBounds(viewport, scene);
    assert.ok(Number.isFinite(bounds.min) && bounds.min > 0 && bounds.min <= 1);
    assert.equal(bounds.max, 4);
    finiteCamera(fitFlowCamera(viewport, scene, 'all')); finiteCamera(fitFlowCamera(viewport, scene));
  }
  finiteCamera(zoomFlowCamera({ x: NaN, y: Infinity, zoom: 0 }, NaN, { x: Infinity, y: NaN }, { min: 0, max: NaN }));
  finiteCamera(panFlowCamera({ x: NaN, y: Infinity, zoom: NaN }, Infinity, NaN));
});

const transformedRect = (rect, before, after) => ({
  x: after.x + (rect.x - before.x) * after.zoom / before.zoom,
  y: after.y + (rect.y - before.y) * after.zoom / before.zoom,
  width: rect.width * after.zoom / before.zoom,
  height: rect.height * after.zoom / before.zoom,
});
const withinPadding = (rect, viewport) => {
  assert.ok(rect.x >= 16 - 1e-9); assert.ok(rect.y >= 16 - 1e-9);
  assert.ok(rect.x + rect.width <= viewport.width - 16 + 1e-9);
  assert.ok(rect.y + rect.height <= viewport.height - 16 + 1e-9);
};

test('revealing a 254-pixel label in a 254-pixel viewport shrinks just enough for padding', () => {
  const camera = { x: 0, y: 24, zoom: 1 }, rect = { x: 0, y: 80, width: 254, height: 44 }, viewport = { width: 254, height: 400 };
  const changed = revealFlowRect(camera, rect, viewport, { min: .01, max: 4 });
  close(changed.zoom, 222 / 254);
  withinPadding(transformedRect(rect, camera, changed), viewport);
  assert.deepEqual(camera, { x: 0, y: 24, zoom: 1 });
});

test('revealing a tall label fits its limiting dimension at any prior zoom and pan', () => {
  const camera = { x: -800, y: -2400, zoom: .6 }, rect = { x: 540, y: -240, width: 80, height: 900 }, viewport = { width: 600, height: 500 };
  const changed = revealFlowRect(camera, rect, viewport, { min: .001, max: 4 });
  close(changed.zoom, camera.zoom * (500 - 32) / 900);
  withinPadding(transformedRect(rect, camera, changed), viewport);
});

test('off-screen labels that already fit only pan the minimum distance on each axis', () => {
  const camera = { x: 12, y: -25, zoom: .4 }, rect = { x: -30, y: 180, width: 80, height: 50 }, viewport = { width: 300, height: 200 };
  const changed = revealFlowRect(camera, rect, viewport, { min: .01, max: 4 });
  assert.equal(changed.zoom, camera.zoom);
  close(changed.x, camera.x + 46); close(changed.y, camera.y - 46);
  withinPadding(transformedRect(rect, camera, changed), viewport);
});

test('revealing an already visible label preserves the original camera object', () => {
  const camera = { x: -20, y: 35, zoom: .4 };
  assert.equal(revealFlowRect(camera, { x: 16, y: 16, width: 268, height: 168 }, { width: 300, height: 200 }, { min: .01, max: 4 }), camera);
});

test('reveal obeys minimum zoom and centres a label that cannot fit within that bound', () => {
  const camera = { x: -10, y: 24, zoom: 1 }, rect = { x: 700, y: 40, width: 500, height: 60 }, viewport = { width: 254, height: 400 };
  const changed = revealFlowRect(camera, rect, viewport, { min: .8, max: 4 });
  assert.equal(changed.zoom, .8);
  const rendered = transformedRect(rect, camera, changed);
  close(rendered.x + rendered.width / 2, viewport.width / 2);
  assert.ok(rendered.y >= 16 && rendered.y + rendered.height <= viewport.height - 16);
  finiteCamera(changed);
});
