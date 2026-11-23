/* R.E.I.G.E.L. loader. Letters orbit in chaos and assemble as real progress advances.
   API: ReigelLoader.show(), .hide(), .track(promise), .mount(element), .drive(mark, progress), .pace(). */
(() => {
  'use strict';

  const WORD = 'R.E.I.G.E.L.';
  const EXIT_MS = 200;
  const FOLLOW_SECONDS = 0.35;
  const FINISH_SECONDS = 0.2;
  const STAGGER = 0.045;
  const LETTER_SPAN = 0.5;
  const GOLDEN_ANGLE = 2.39996;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let overlay = null;
  let overlayEngine = null;
  let pending = 0;
  let hideTimer = 0;

  const clamp = value => Math.min(1, Math.max(0, value));
  const ease = value => value < 0.5 ? 4 * value ** 3 : 1 - (-2 * value + 2) ** 3 / 2;

  /** Seconds a typical step takes on this connection; a hint where the browser reports it. */
  function pace() {
    const connection = navigator.connection;
    if (!connection) return 2.2;
    if (connection.saveData) return 5;
    return {'slow-2g': 9, '2g': 7, '3g': 3.5, '4g': 1.4}[connection.effectiveType] || 2.2;
  }

  /** Animate a mark from chaos to the word; `progress(now)` returns the real 0..1 target. */
  function drive(mark, progress) {
    const glyphs = [...mark.querySelectorAll('.rl-glyph')];
    const line = mark.querySelector('.rl-line');
    const word = mark.querySelector('.rl-word');
    if (reduceMotion.matches || !glyphs.length) return {finish: () => Promise.resolve(), settle() {}};

    let shown = 0;
    let target = 0;
    let finishing = false;
    let frame = 0;
    let last = performance.now();
    let settled = false;
    let resolveFinish = null;
    let slots = [];
    let radius = 2;
    const orbits = glyphs.map((_, index) => ({
      angle: index * GOLDEN_ANGLE,
      ring: 0.46 + 0.54 * ((index * 7) % glyphs.length) / (glyphs.length - 1),
      speed: (0.9 + 1.5 * ((index * 5) % glyphs.length) / (glyphs.length - 1)) * (index % 2 ? -1 : 1),
      start: ((index * 5) % glyphs.length) * STAGGER,
    }));

    function measure() {
      const size = parseFloat(getComputedStyle(mark).fontSize) || 40;
      const holder = mark.closest('.rl-loader, .ps-loader') || mark.parentElement;
      slots = glyphs.map(glyph => (glyph.offsetLeft - word.offsetLeft + glyph.offsetWidth / 2 - word.offsetWidth / 2) / size);
      radius = Math.min(4.2, Math.max(1.4, Math.min(holder.clientWidth * 0.46, holder.clientHeight * 0.42) / size - 0.6));
    }

    function settle() {
      if (settled) return;
      settled = true;
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', measure);
      document.removeEventListener('visibilitychange', onVisibility);
      mark.classList.remove('rl-active');
      for (const glyph of glyphs) {
        glyph.style.transform = '';
        glyph.style.opacity = '';
      }
      if (line) line.style.transform = '';
      if (resolveFinish) resolveFinish();
    }

    function onVisibility() {
      // A hidden page receives no frames, so a finishing loader must not wait for one.
      if (document.hidden && finishing) settle();
      else if (!document.hidden && !settled) last = performance.now();
    }

    function render(now) {
      if (settled) return;
      const delta = Math.min(0.25, (now - last) / 1000);
      last = now;
      target = finishing ? 1 : Math.max(target, clamp(progress(now)));
      shown += (target - shown) * (1 - Math.exp(-delta / (finishing ? FINISH_SECONDS : FOLLOW_SECONDS)));
      const time = now / 1000;
      glyphs.forEach((glyph, index) => {
        const orbit = orbits[index];
        const formed = ease(clamp((shown - orbit.start) / LETTER_SPAN));
        const free = 1 - formed;
        const angle = orbit.angle + orbit.speed * time + 0.35 * Math.sin(time * 1.7 + index);
        const reach = radius * orbit.ring * (1 + 0.1 * Math.sin(time * 2.3 + index * 1.3));
        const x = (Math.cos(angle) * reach - slots[index]) * free;
        const y = Math.sin(angle) * reach * 0.82 * free;
        const spin = Math.sin(time * 1.4 + index) * 140 * free;
        glyph.style.transform = `translate3d(${x.toFixed(3)}em,${y.toFixed(3)}em,0) rotate(${spin.toFixed(1)}deg)`;
        glyph.style.opacity = (0.42 + 0.58 * formed).toFixed(3);
      });
      if (line) line.style.transform = `scaleX(${shown.toFixed(4)})`;
      if (finishing && shown > 0.995) {
        settle();
        return;
      }
      frame = requestAnimationFrame(render);
    }

    measure();
    mark.classList.add('rl-active');
    window.addEventListener('resize', measure, {passive: true});
    document.addEventListener('visibilitychange', onVisibility);
    render(last);

    return {
      settle,
      finish() {
        if (settled || document.hidden) {
          settle();
          return Promise.resolve();
        }
        finishing = true;
        return new Promise(resolve => { resolveFinish = resolve; });
      },
    };
  }

  function build(variant, label) {
    const root = document.createElement('div');
    root.className = `rl-loader rl-loader--${variant}`;
    root.setAttribute('role', 'status');
    const mark = document.createElement('div');
    mark.className = 'rl-mark';
    mark.setAttribute('aria-hidden', 'true');
    const word = document.createElement('div');
    word.className = 'rl-word';
    for (const char of WORD) {
      const glyph = document.createElement('span');
      glyph.className = `rl-glyph rl-glyph--${char === '.' ? 'dot' : 'letter'}`;
      glyph.textContent = char;
      word.append(glyph);
    }
    const line = document.createElement('span');
    line.className = 'rl-line';
    const status = document.createElement('span');
    status.className = 'rl-status';
    status.textContent = label;
    mark.append(word, line);
    root.append(mark, status);
    return root;
  }

  /** Without a measurable source, advance by connection speed and never claim completion. */
  function estimated() {
    const started = performance.now();
    const seconds = pace();
    return now => 0.88 * (1 - Math.exp(-(now - started) / 1000 / seconds));
  }

  function closeOverlay() {
    if (!overlay || pending) return;
    overlay.classList.add('rl-leaving');
    hideTimer = window.setTimeout(() => {
      if (typeof overlay.hidePopover === 'function' && overlay.matches(':popover-open')) overlay.hidePopover();
      overlay.hidden = true;
      overlay.classList.remove('rl-leaving');
      document.documentElement.classList.remove('rl-locked');
    }, EXIT_MS);
  }

  /** Show the full-screen loader. Nested calls stay open until each one is hidden. */
  function show({label = 'Cargando R.E.I.G.E.L.', progress} = {}) {
    window.clearTimeout(hideTimer);
    if (!overlay) {
      overlay = build('overlay', label);
      overlay.hidden = true;
      if (typeof overlay.showPopover === 'function') overlay.setAttribute('popover', 'manual');
      document.body.append(overlay);
    }
    overlay.querySelector('.rl-status').textContent = label;
    pending += 1;
    overlay.classList.remove('rl-leaving');
    if (overlay.hidden) {
      overlay.hidden = false;
      document.documentElement.classList.add('rl-locked');
      // The top layer keeps the loader above an open modal <dialog>.
      if (typeof overlay.showPopover === 'function' && !overlay.matches(':popover-open')) overlay.showPopover();
      overlayEngine = drive(overlay.querySelector('.rl-mark'), progress || estimated());
    }
  }

  function hide() {
    if (!pending) return;
    pending -= 1;
    if (pending || !overlayEngine) return;
    overlayEngine.finish().then(closeOverlay);
  }

  /** Keep the loader visible while a promise runs; its result or error passes through. */
  async function track(promise, options) {
    show(options);
    try {
      return await promise;
    } finally {
      hide();
    }
  }

  /** Render the loader inside a container, for a panel or section that is loading. */
  function mount(element, {label = element.dataset.reigelLabel || 'Cargando R.E.I.G.E.L.', progress} = {}) {
    const loader = build('inline', label);
    element.replaceChildren(loader);
    const engine = drive(loader.querySelector('.rl-mark'), progress || estimated());
    return () => engine.finish().then(() => loader.remove());
  }

  window.ReigelLoader = {show, hide, track, mount, drive, pace};

  const mountDeclared = () => document.querySelectorAll('[data-reigel-loader]').forEach(element => mount(element));
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountDeclared, {once: true});
  else mountDeclared();
})();
