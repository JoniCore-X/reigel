'use strict';

// Tres detalles de la placa en /soluciones ([data-sc-macro]). Sin este archivo,
// o con movimiento reducido, quedan como lista estática. Aquí solo se lee la
// posición de la página (escucha pasiva): nunca se intercepta la rueda ni el
// tacto, y subir recorre los detalles al revés.
(() => {
  const section = document.querySelector('[data-sc-macro]');
  if (!section) return;
  const track = section.querySelector('.sc-macro-track');
  const stage = section.querySelector('.sc-macro-stage');
  const items = [...section.querySelectorAll('.sc-macro-item')];
  const header = document.querySelector('.public-header');
  if (!track || !stage || items.length < 2) return;

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  let frame = 0;
  let live = false;
  let top = 0;

  function measureTop() {
    top = header ? Math.round(header.getBoundingClientRect().height) : 0;
    section.style.setProperty('--sc-top', `${top}px`);
  }

  function render() {
    frame = 0;
    if (!live) return;
    const box = track.getBoundingClientRect();
    const travel = Math.max(1, box.height - stage.offsetHeight);
    const progress = clamp((top - box.top) / travel, 0, 1);
    const position = progress * items.length;
    let active = 0;
    let best = -1;
    items.forEach((item, index) => {
      let distance = position - (index + 0.5);
      if (index === 0) distance = Math.max(0, distance);
      if (index === items.length - 1) distance = Math.min(0, distance);
      const opacity = clamp((0.6 - Math.abs(distance)) / 0.2, 0, 1);
      const zoom = 1.05 - 0.05 * clamp(position - index, 0, 1);
      item.style.setProperty('--o', opacity.toFixed(3));
      item.style.setProperty('--s', zoom.toFixed(4));
      if (opacity > best) { best = opacity; active = index; }
    });
    section.dataset.active = String(active);
  }

  // Una pestaña oculta no entrega cuadros: ahí se calcula en el acto.
  function schedule() {
    if (document.visibilityState !== 'visible') {
      render();
      return;
    }
    if (!frame) frame = window.requestAnimationFrame(render);
  }

  function setLive(on) {
    live = on;
    section.classList.toggle('sc-macro-live', on);
    if (on) {
      measureTop();
      schedule();
      return;
    }
    delete section.dataset.active;
    items.forEach(item => {
      item.style.removeProperty('--o');
      item.style.removeProperty('--s');
    });
  }

  setLive(!reduced.matches);
  window.addEventListener('scroll', schedule, { passive: true });
  window.addEventListener('resize', () => { if (live) { measureTop(); schedule(); } }, { passive: true });
  reduced.addEventListener?.('change', () => setLive(!reduced.matches));
})();

// Revelado de los bloques de imágenes de referencia ([data-sc-reveal]) en las
// páginas públicas. Sin este archivo todo queda visible y completo; en una
// página sin esos bloques no hace nada.
(() => {
  const blocks = [...document.querySelectorAll('[data-sc-reveal]')];
  if (!blocks.length) return;

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let observer = null;

  function showAll() {
    observer?.disconnect();
    observer = null;
    blocks.forEach(block => {
      block.classList.add('is-in');
      block.classList.remove('sc-armed');
    });
  }

  // Una pestaña oculta no entrega observaciones: ahí el contenido queda visible.
  if (reduced.matches || document.visibilityState !== 'visible' || !('IntersectionObserver' in window)) {
    showAll();
    return;
  }

  blocks.forEach(block => block.classList.add('sc-armed'));
  observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add('is-in');
      observer?.unobserve(entry.target);
    });
  }, { rootMargin: '0px 0px -10% 0px', threshold: 0.06 });
  blocks.forEach(block => observer.observe(block));

  reduced.addEventListener?.('change', () => { if (reduced.matches) showAll(); });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') showAll();
  });
})();
