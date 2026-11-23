/* Aparta el acceso flotante cuando estorba: al leer hacia abajo en pantallas
   compactas y siempre que quede sobre un control. Solo cambia su presentación. */
(() => {
  'use strict';

  const launcher = document.querySelector('.chat-launcher');
  if (!launcher) return;

  const compact = window.matchMedia('(max-width: 900px)');
  const CONTROLS = 'a[href], button, input, select, textarea, label, summary, [role="button"]';
  const TOP_ZONE = 120;
  const MIN_DELTA = 6;
  const BOTTOM_ZONE = 24;
  const MARGIN = 6;
  const SETTLE_MS = 700;
  let lastY = window.scrollY;
  let reading = false;
  let queued = false;
  let settleTimer = 0;

  /* offset* ignora el desplazamiento visual, así que mide su posición de reposo. */
  function coversControl() {
    const left = launcher.offsetLeft - MARGIN;
    const top = launcher.offsetTop - MARGIN;
    const right = left + launcher.offsetWidth + MARGIN * 2;
    const bottom = top + launcher.offsetHeight + MARGIN * 2;
    const points = [
      [(left + right) / 2, (top + bottom) / 2],
      [left, top], [right - 1, top], [left, bottom - 1], [right - 1, bottom - 1],
    ];
    return points.some(([x, y]) => document.elementsFromPoint(x, y).some(element => (
      !launcher.contains(element) && element.closest('main, footer') && element.closest(CONTROLS)
    )));
  }

  function update() {
    queued = false;
    if (document.querySelector('dialog[open]')) return;
    const y = window.scrollY;
    const delta = y - lastY;
    if (Math.abs(delta) >= MIN_DELTA) {
      reading = compact.matches && delta > 0;
      lastY = y;
    }
    const end = document.documentElement.scrollHeight - window.innerHeight - BOTTOM_ZONE;
    if (y < TOP_ZONE || y >= end || !compact.matches) reading = false;
    document.body.classList.toggle('launcher-away', reading || coversControl());
  }

  function schedule() {
    if (queued) return;
    queued = true;
    window.requestAnimationFrame(update);
  }

  /* Las secciones se revelan con movimiento: vuelve a medir cuando la página se detiene. */
  function onScroll() {
    schedule();
    window.clearTimeout(settleTimer);
    settleTimer = window.setTimeout(schedule, SETTLE_MS);
  }

  window.addEventListener('scroll', onScroll, {passive: true});
  window.addEventListener('resize', schedule, {passive: true});
  compact.addEventListener('change', schedule);
  window.addEventListener('load', schedule, {once: true});
  update();
})();
