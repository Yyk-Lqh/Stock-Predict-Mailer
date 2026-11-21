/* Run via gstack browse eval against a fresh tests/browser_console_fixture.py on :8768. */
(async () => {
  const assert = (value, message) => { if (!value) throw Error(message); };
  const close = (a, b) => Math.abs(a - b) < .05;
  assert(location.hostname === '127.0.0.1' && location.port === '8768', 'Use the disposable fixture');
  assert(innerWidth >= 1200, 'Use a desktop viewport at least 1200px wide');
  const canvas = document.getElementById('desktop-workflow-canvas');
  window.DesktopWorkbench.setMode('focus');
  const collapse = document.querySelector('.desktop-nav-collapse');
  const wasCollapsed = collapse.getAttribute('aria-expanded') === 'false';
  if (!wasCollapsed) collapse.click();
  const navButtons = [...document.querySelectorAll('.topbar .nav button:not([hidden])')];
  assert(navButtons.length >= 9, 'All navigation modules must be available when collapsed');
  for (const button of navButtons) {
    const icon = button.querySelector('.desktop-nav-icon');
    assert(button.getAttribute('aria-label') && icon?.getClientRects().length && getComputedStyle(icon).opacity === '1', 'Collapsed navigation must show a visible icon and preserve its accessible label');
  }
  if (!wasCollapsed) collapse.click();
  const viewportTools = document.querySelector('.desktop-flow-viewport-tools');
  assert(viewportTools.closest('.desktop-flow-toolbar') && !canvas.contains(viewportTools), 'Zoom and fit must be in the top toolbar');
  const surface = document.getElementById('desktop-workflow-surface');
  const svg = document.getElementById('desktop-workflow-edges');
  const fit = () => document.querySelector('[data-viewport-action="fit"]').click();
  const model = () => canvas.querySelector('[data-workflow-node="model"]');
  const edge = () => svg.querySelector('[data-edge-id="model-prediction"]');
  const camera = () => new DOMMatrix(surface.style.transform);
  const pointer = (target, type, x, y) => {
    target.dispatchEvent(new PointerEvent(type, {pointerId: 1, button: 0, clientX: x, clientY: y, bubbles: true, cancelable: true}));
  };
  const move = (target, dx, dy, end = 'pointerup') => {
    const rect = target.getBoundingClientRect(), x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
    pointer(target, 'pointerdown', x, y);
    pointer(canvas, 'pointermove', x + dx, y + dy);
    pointer(canvas, end, x + dx, y + dy);
  };
  const checkGrid = () => {
    const style = getComputedStyle(canvas), {a, e, f} = camera();
    const spacing = parseFloat(style.getPropertyValue('--desktop-grid-spacing'));
    const x = parseFloat(style.getPropertyValue('--desktop-grid-x'));
    const y = parseFloat(style.getPropertyValue('--desktop-grid-y'));
    assert(style.backgroundRepeat === 'repeat, no-repeat' && style.backgroundImage.startsWith('radial-gradient'), 'Full canvas must paint repeating dots');
    assert(close(x + spacing / 2, e % spacing) && close(y + spacing / 2, f % spacing), 'Grid phase must follow the camera');
    const worldSpacing = spacing / (18 * a);
    assert(spacing >= 8 && close(Math.log2(worldSpacing), Math.round(Math.log2(worldSpacing))), 'Grid spacing must follow zoom in world coordinates');
    assert(getComputedStyle(surface).backgroundImage === 'none', 'The transformed node plane must have no finite grid layer');
  };

  const originalCapture = canvas.setPointerCapture;
  canvas.setPointerCapture = () => {}; // Synthetic pointer events cannot acquire native capture.
  try {
    fit();
    const original = camera();
    move(canvas, 4100, -3400);
    assert(close(camera().e, original.e + 4100) && close(camera().f, original.f - 3400), 'Canvas pan must extend past the old bounds');
    checkGrid();
    move(canvas, -8100, 6800);
    checkGrid();
    const rect = canvas.getBoundingClientRect();
    const before = camera();
    const wheel = new WheelEvent('wheel', {deltaY: -100, clientX: rect.left + rect.width / 3, clientY: rect.top + rect.height / 3, bubbles: true, cancelable: true});
    const x = wheel.clientX - rect.left, y = wheel.clientY - rect.top;
    canvas.dispatchEvent(wheel);
    const after = camera();
    assert(after.a > before.a && close((x - before.e) / before.a, (x - after.e) / after.a) && close((y - before.f) / before.d, (y - after.f) / after.d), 'Zoom must keep the pointer anchored');
    checkGrid();

    fit();
    const oldEdge = edge().getAttribute('d');
    move(model(), -3500, -2700);
    assert(parseFloat(model().style.left) < -2000 && parseFloat(model().style.top) < -1500, 'Node drag must support negative world coordinates');
    assert(edge().getAttribute('d') !== oldEdge, 'Edges must follow a moved node');
    const negative = model().style.left;
    move(model(), 350, 250, 'pointercancel');
    assert(model().style.left === negative && !model().classList.contains('dragging'), 'Canceled drag must restore the saved position');
    model().dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowLeft', bubbles: true, cancelable: true}));
    assert(close(parseFloat(model().style.left), parseFloat(negative) - 8), 'Keyboard moves must also support negative coordinates');
    document.getElementById('desktop-workflow-undo').click();
    assert(model().style.left === negative, 'Undo must restore the layout before a move');

    move(model(), 6400, 6300);
    const position = {x: parseFloat(model().style.left), y: parseFloat(model().style.top)};
    assert(position.x > 1720 && position.y > 500, 'Node drag must extend beyond the old maximum');
    fit();
    const viewport = canvas.getBoundingClientRect();
    for (const node of canvas.querySelectorAll('[data-workflow-node]')) {
      const bounds = node.getBoundingClientRect();
      assert(bounds.left >= viewport.left && bounds.top >= viewport.top && bounds.right <= viewport.right && bounds.bottom <= viewport.bottom, 'Fit must include every moved node');
    }
    const start = edge().getPointAtLength(0).matrixTransform(edge().getScreenCTM());
    const bounds = model().getBoundingClientRect();
    assert(close(start.x, (bounds.left + bounds.right) / 2) && close(start.y, bounds.top), 'SVG must use the same viewport as the nodes');
    const saved = document.getElementById('desktop-workflow-save');
    saved.click();
    const graph = JSON.parse(localStorage.getItem('stock_predict_mailer.desktop.workflow.v1'));
    assert(close(graph.nodes.find(node => node.id === 'model').position.x, position.x), 'Saving must preserve off-origin coordinates');
    checkGrid();

    const startPan = camera().e;
    pointer(model(), 'pointerdown', bounds.left + bounds.width / 2, bounds.top + bounds.height / 2);
    pointer(canvas, 'pointermove', viewport.left + 2, viewport.top + viewport.height / 2);
    await new Promise(resolve => setTimeout(resolve, 250));
    assert(camera().e > startPan + 10, 'Dragging a node to an edge must automatically pan the viewport');
    const dragged = model().getBoundingClientRect();
    assert(close(dragged.left + dragged.width / 2, viewport.left + 2), 'Dragged node must stay under the pointer during auto-pan');
    pointer(canvas, 'pointercancel', viewport.left + 2, viewport.top + viewport.height / 2);
    assert(close(parseFloat(model().style.left), position.x), 'Cancel must restore the node after auto-pan');
    fit();
    document.body.dataset.desktopCanvasCheck = 'passed';
    return 'Passed: navigation, toolbar, grid, pan, zoom, drag, keyboard, edges, fit, save and auto-pan.';
  } finally {
    canvas.setPointerCapture = originalCapture;
  }
})().catch(error => { document.body.dataset.desktopCanvasCheck = error.message; });
