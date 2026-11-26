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

// Secuencia del apagón en /captacion ([data-sc-outage]). Sin este archivo, con
// movimiento reducido o si el escenario no cabe en la ventana, queda la foto
// con su título y sus textos. Aquí el escenario se fija y cinco valores (0 a 1)
// salen de la posición de la página: red, casas sin respaldo, batería, paso a
// la foto y título. Solo se lee la posición (escucha pasiva): subir recorre la
// secuencia al revés y nunca se intercepta la rueda ni el tacto.
(() => {
  const section = document.querySelector('[data-sc-outage]');
  if (!section) return;
  const track = section.querySelector('.sc-out-track');
  const stage = section.querySelector('.sc-out-stage');
  const header = document.querySelector('.public-header');
  if (!track || !stage) return;

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const ramp = (value, from, to) => clamp((value - from) / (to - from), 0, 1);
  const VALUES = ['--g', '--n', '--b', '--x', '--t'];
  let frame = 0;
  let live = false;
  let pin = 0;
  let height = 0;

  // Devuelve false si el escenario no cabe bajo el encabezado.
  function measure() {
    const top = header ? Math.round(header.getBoundingClientRect().height) : 0;
    const view = window.innerHeight || 1;
    section.style.setProperty('--sc-top', `${top}px`);
    height = stage.offsetHeight;
    if (height > view - top + 1) return false;
    pin = top + (window.innerWidth > 900 ? Math.max(0, Math.round((view - top - height) / 2)) : 0);
    section.style.setProperty('--sc-out-sh', `${height}px`);
    section.style.setProperty('--sc-out-top', `${pin}px`);
    return true;
  }

  function render() {
    frame = 0;
    if (!live) return;
    const view = window.innerHeight || 1;
    const box = track.getBoundingClientRect();
    if (box.bottom < -view || box.top > view * 2) return;
    const progress = clamp((pin - box.top) / Math.max(1, box.height - height), 0, 1);
    const values = [
      1 - ramp(progress, 0.12, 0.26),
      1 - ramp(progress, 0.32, 0.46),
      ramp(progress, 0.48, 0.6),
      ramp(progress, 0.7, 0.86),
      ramp(progress, 0.84, 0.96),
    ];
    VALUES.forEach((name, index) => section.style.setProperty(name, values[index].toFixed(3)));
    const step = progress < 0.16 ? 0 : progress < 0.36 ? 1 : progress < 0.5 ? 2 : progress < 0.74 ? 3 : 4;
    section.dataset.step = String(step);
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
    section.classList.toggle('sc-out-live', on);
    if (on && measure()) {
      schedule();
      return;
    }
    live = false;
    section.classList.remove('sc-out-live');
    delete section.dataset.step;
    [...VALUES, '--sc-out-sh', '--sc-out-top'].forEach(name => section.style.removeProperty(name));
  }

  setLive(!reduced.matches);
  window.addEventListener('scroll', schedule, { passive: true });
  window.addEventListener('resize', () => setLive(!reduced.matches), { passive: true });
  reduced.addEventListener?.('change', () => setLive(!reduced.matches));
})();

// Línea de tiempo de /proceso ([data-sc-journey]). Sin este archivo las cinco
// etapas muestran su detalle y la línea está completa. Aquí cada título pasa
// a ser un botón que abre o cierra su detalle (en horizontal, uno a la vez) y
// la línea se rellena según la posición de la página: solo se lee esa
// posición (escucha pasiva) y subir la vacía. Con movimiento reducido la
// línea queda completa; los botones siguen funcionando.
(() => {
  const section = document.querySelector('[data-sc-journey]');
  if (!section) return;
  const rail = section.querySelector('.sc-jr-rail');
  const stages = rail ? [...rail.children] : [];
  const parts = stages.map(stage => ({
    stage,
    title: stage.querySelector('h3'),
    more: stage.querySelector('.sc-jr-more'),
    node: stage.querySelector('.sc-jr-node'),
    top: stage.querySelector('.sc-jr-top'),
  }));
  if (stages.length < 2 || parts.some(part => !part.title || !part.more || !part.node || !part.top)) return;

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const horizontal = () => window.getComputedStyle(rail).display === 'grid';

  function setOpen(part, on) {
    part.button.setAttribute('aria-expanded', String(on));
    part.more.hidden = !on;
    part.stage.classList.toggle('is-open', on);
    part.cue.lastChild.textContent = on ? 'Ocultar detalle' : 'Ver detalle';
  }

  parts.forEach(part => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'sc-jr-toggle';
    button.setAttribute('aria-controls', part.more.id);
    while (part.title.firstChild) button.append(part.title.firstChild);
    part.title.append(button);
    const cue = document.createElement('span');
    cue.className = 'sc-jr-cue';
    cue.setAttribute('aria-hidden', 'true');
    cue.append(document.createElement('i'), document.createTextNode(''));
    part.top.append(cue);
    part.button = button;
    part.cue = cue;
    part.more.setAttribute('role', 'region');
    part.more.setAttribute('aria-labelledby', part.title.id);
    button.addEventListener('click', () => {
      const on = button.getAttribute('aria-expanded') !== 'true';
      if (on && horizontal()) parts.forEach(other => { if (other !== part) setOpen(other, false); });
      setOpen(part, on);
      schedule();
    });
  });
  parts.forEach((part, index) => setOpen(part, index === 0));
  rail.classList.add('sc-jr-live');

  let frame = 0;
  let live = false;

  function render() {
    frame = 0;
    if (!live) return;
    const view = window.innerHeight || 1;
    const box = rail.getBoundingClientRect();
    if (box.bottom < -view || box.top > view * 2) return;
    const across = horizontal();
    const progress = across
      ? clamp((view * 0.86 - box.top) / (view * 0.5), 0, 1)
      : clamp((view * 0.72 - box.top) / Math.max(1, box.height), 0, 1);
    const reach = progress * (across ? box.width : box.height) + 1;
    rail.style.setProperty('--p', progress.toFixed(4));
    parts.forEach(part => {
      const dot = part.node.getBoundingClientRect();
      const place = across ? dot.left + dot.width / 2 - box.left : dot.top + dot.height / 2 - box.top;
      part.stage.classList.toggle('is-on', place <= reach);
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
    rail.classList.toggle('sc-jr-scrub', on);
    if (on) {
      schedule();
      return;
    }
    rail.style.removeProperty('--p');
    stages.forEach(stage => stage.classList.remove('is-on'));
  }

  // Al pasar a horizontal queda abierto un solo detalle.
  function tidy() {
    if (horizontal()) {
      const open = parts.filter(part => part.stage.classList.contains('is-open'));
      open.slice(1).forEach(part => setOpen(part, false));
    }
    schedule();
  }

  setLive(!reduced.matches);
  window.addEventListener('scroll', schedule, { passive: true });
  window.addEventListener('resize', tidy, { passive: true });
  reduced.addEventListener?.('change', () => setLive(!reduced.matches));
})();
