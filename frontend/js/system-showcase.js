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

// Capítulos de ingeniería en /empresa ([data-sc-eng]): cada [data-sc-scrub]
// recibe --p (0 a 1) según su paso por la ventana. "enter" se completa al
// entrar; "pass" recorre todo el cruce. Solo se lee la posición (escucha
// pasiva), es reversible y con movimiento reducido no se escribe nada: quedan
// los valores estáticos de la hoja de estilos.
(() => {
  const section = document.querySelector('[data-sc-eng]');
  if (!section) return;
  const targets = [...section.querySelectorAll('[data-sc-scrub]')];
  if (!targets.length) return;

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  let frame = 0;
  let live = false;

  function render() {
    frame = 0;
    if (!live) return;
    const view = window.innerHeight || 1;
    const area = section.getBoundingClientRect();
    if (area.bottom < -view || area.top > view * 2) return;
    targets.forEach(target => {
      const box = target.getBoundingClientRect();
      const progress = target.dataset.scScrub === 'enter'
        ? clamp((view * 0.92 - box.top) / (view * 0.6), 0, 1)
        : clamp((view - box.top) / (view + box.height), 0, 1);
      target.style.setProperty('--p', progress.toFixed(4));
      if (!target.matches('.sc-eng-steps')) return;
      const steps = [...target.children];
      steps.forEach((step, index) => step.classList.toggle('is-on', progress >= (index + 0.3) / steps.length));
    });
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
    targets.forEach(target => {
      if (target.matches('.sc-eng-steps')) target.classList.toggle('sc-eng-live', on);
      if (on) return;
      target.style.removeProperty('--p');
      [...target.children].forEach(child => child.classList.remove('is-on'));
    });
    if (on) schedule();
  }

  setLive(!reduced.matches);
  window.addEventListener('scroll', schedule, { passive: true });
  window.addEventListener('resize', schedule, { passive: true });
  reduced.addEventListener?.('change', () => setLive(!reduced.matches));
})();

// Indicadores de la aplicación en /soluciones ([data-sc-tabs]). Sin este
// archivo los tres bloques quedan a la vista, uno tras otro, y la lista de
// pestañas sigue oculta. Aquí se convierten en pestañas (flechas, Inicio y
// Fin) y se enciende la marca externa junto al teléfono relacionado: la
// captura no se toca.
(() => {
  const root = document.querySelector('[data-sc-tabs]');
  if (!root) return;
  const list = root.querySelector('[role="tablist"]');
  const tabs = [...root.querySelectorAll('[role="tab"]')];
  const panels = tabs.map(tab => document.getElementById(tab.getAttribute('aria-controls')));
  const pins = [...(root.closest('.sc-app')?.querySelectorAll('[data-sc-pin]') || [])];
  if (!list || tabs.length < 2 || panels.some(panel => !panel)) return;

  function select(index, focus) {
    tabs.forEach((tab, position) => {
      const on = position === index;
      tab.setAttribute('aria-selected', String(on));
      tab.tabIndex = on ? 0 : -1;
      panels[position].classList.toggle('is-active', on);
    });
    pins.forEach(pin => pin.classList.toggle('is-active', pin.dataset.scPin === tabs[index].dataset.scTab));
    if (focus) tabs[index].focus();
  }

  const KEYS = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => select(index, false));
    tab.addEventListener('keydown', event => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      let next = -1;
      if (event.key in KEYS) next = (index + KEYS[event.key] + tabs.length) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next < 0) return;
      event.preventDefault();
      select(next, true);
    });
  });
  panels.forEach((panel, index) => {
    panel.setAttribute('role', 'tabpanel');
    panel.setAttribute('aria-labelledby', tabs[index].id);
    panel.tabIndex = 0;
  });
  list.hidden = false;
  root.classList.add('sc-app-live');
  select(Math.max(0, tabs.findIndex(tab => tab.getAttribute('aria-selected') === 'true')), false);
})();
