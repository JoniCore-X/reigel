/* R.E.I.G.E.L. loader. Letters orbit in harmonic chaos and assemble once the page is ready.
   API: ReigelLoader.show(), .hide(), .track(promise), .mount(element), .drive(mark, progress), .pace(). */
(() => {
  'use strict';

  const WORD = 'R.E.I.G.E.L.';
  const EXIT_MS = 200;
  const FOLLOW_SECONDS = 0.35;
  const TICK_MS = 100;
  const CYCLE_MS = 2800;
  const LAND_MS = 640;
  const LAND_STEP_MS = 32;
  const HOLD_MS = 260;
  const LAND_EASING = 'cubic-bezier(.16, 1, .3, 1)';
  const TURNS = [1, -2, 3, -1, 2, -3, 1, -3, 2, -1, 3, -2];
  const RINGS = [
    {reach: 0.46, scale: 0.72, opacity: 0.78},
    {reach: 0.73, scale: 0.86, opacity: 0.9},
    {reach: 1, scale: 1, opacity: 1},
  ];
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let overlay = null;
  let overlayEngine = null;
  let pending = 0;
  let hideTimer = 0;

  const clamp = value => Math.min(1, Math.max(0, value));

  /** Skip the live blur where it could cost more than it adds. */
  function isConstrained() {
    const connection = navigator.connection;
    return Boolean(connection && connection.saveData)
      || (navigator.hardwareConcurrency || 8) <= 4
      || (navigator.deviceMemory || 8) <= 2;
  }

  /** Seconds a typical step takes on this connection; a hint where the browser reports it. */
  function pace() {
    const connection = navigator.connection;
    if (!connection) return 2.2;
    if (connection.saveData) return 5;
    return {'slow-2g': 9, '2g': 7, '3g': 3.5, '4g': 1.4}[connection.effectiveType] || 2.2;
  }

  /** Harmonic orbits: every letter turns a whole number of times per cycle, so the
      apparent chaos returns to one exact formation, where the word can assemble.
      The compositor runs the motion; a slow timer only reads real progress. */
  function drive(mark, progress, {cycle = CYCLE_MS, align = false} = {}) {
    const glyphs = [...mark.querySelectorAll('.rl-glyph')];
    const line = mark.querySelector('.rl-line');
    const word = mark.querySelector('.rl-word');
    if (reduceMotion.matches || !glyphs.length || typeof mark.animate !== 'function') {
      return {finish: () => Promise.resolve(), settle() {}};
    }

    const holder = mark.closest('.rl-loader, .ps-loader') || mark.parentElement;
    const startTime = document.timeline.currentTime ?? performance.now();
    let shown = 0;
    let target = 0;
    let finishing = false;
    let settled = false;
    let resolveFinish = null;
    let tickTimer = 0;
    let finishTimer = 0;
    let last = performance.now();
    const timers = new Set();
    if (isConstrained()) holder.classList.add('rl-lite');

    const parts = glyphs.map((glyph, index) => {
      const char = glyph.textContent;
      const face = document.createElement('span');
      face.className = 'rl-face';
      face.textContent = char;
      glyph.replaceChildren(face);
      const turns = TURNS[index % TURNS.length];
      const from = index * (360 / glyphs.length);
      const to = from + 360 * turns;
      const spin = glyph.animate([{rotate: `${from}deg`}, {rotate: `${to}deg`}], {duration: cycle, iterations: Infinity});
      const counter = face.animate([{rotate: `${-from}deg`}, {rotate: `${-to}deg`}], {duration: cycle, iterations: Infinity});
      const roll = (index % 2 ? -1 : 1) * 180;
      const tumble = face.animate(
        [{transform: 'rotate(0deg)'}, {transform: `rotate(${roll}deg)`}, {transform: 'rotate(0deg)'}],
        {duration: cycle, iterations: Infinity, easing: 'ease-in-out'},
      );
      spin.startTime = startTime;
      counter.startTime = startTime;
      tumble.startTime = startTime;
      const ring = RINGS[(index * 2) % RINGS.length];
      face.style.scale = String(ring.scale);
      glyph.style.opacity = String(ring.opacity);
      return {glyph, face, char, spin, counter, tumble, breath: null, landing: [], ring, index, slot: 0, formed: false};
    });

    function measure() {
      const size = parseFloat(getComputedStyle(mark).fontSize) || 40;
      const radius = Math.min(4.2, Math.max(1.4, Math.min(holder.clientWidth * 0.46, holder.clientHeight * 0.42) / size - 0.6));
      mark.style.setProperty('--rl-orbit', `${(radius * 2).toFixed(3)}em`);
      for (const part of parts) {
        const {glyph} = part;
        part.slot = (glyph.offsetLeft + glyph.offsetWidth / 2 - word.offsetWidth / 2) / size; // .rl-word is the offset parent.
        if (part.formed) continue;
        glyph.style.translate = `${(-part.slot).toFixed(3)}em 0`;
        const reach = radius * part.ring.reach;
        const keys = [reach, reach * 1.09, reach].map(value => ({transform: `translateX(${value.toFixed(3)}em)`}));
        if (part.breath) {
          part.breath.effect.setKeyframes(keys);
        } else {
          part.breath = glyph.animate(keys, {duration: cycle, iterations: Infinity, easing: 'ease-in-out'});
          part.breath.startTime = startTime;
        }
      }
    }

    function land(part, delay) {
      part.formed = true;
      const {glyph, face} = part;
      const reach = getComputedStyle(glyph).transform;
      const tilt = getComputedStyle(face).transform;
      part.breath.cancel();
      part.tumble.cancel();
      const timing = {duration: LAND_MS, delay, easing: LAND_EASING, fill: 'both'};
      part.landing = [
        glyph.animate([
          {transform: reach === 'none' ? 'translateX(0em)' : reach, translate: `${(-part.slot).toFixed(3)}em 0`, opacity: part.ring.opacity},
          {transform: 'translateX(0em)', translate: '0em 0', opacity: 1},
        ], timing),
        face.animate([
          {transform: tilt === 'none' ? 'rotate(0deg)' : tilt, scale: part.ring.scale},
          {transform: 'rotate(0deg)', scale: 1},
        ], timing),
      ];
      const timer = window.setTimeout(() => {
        timers.delete(timer);
        part.spin.cancel();
        part.counter.cancel();
      }, delay + LAND_MS);
      timers.add(timer);
    }

    function settle() {
      if (settled) return;
      settled = true;
      window.clearInterval(tickTimer);
      window.clearTimeout(finishTimer);
      for (const timer of timers) window.clearTimeout(timer);
      window.removeEventListener('resize', measure);
      document.removeEventListener('visibilitychange', onVisibility);
      mark.classList.remove('rl-active', 'rl-forming');
      mark.style.removeProperty('--rl-orbit');
      for (const part of parts) {
        for (const animation of [part.spin, part.counter, part.tumble, part.breath, ...part.landing]) {
          if (animation) animation.cancel();
        }
        part.glyph.textContent = part.char;
        part.glyph.style.translate = '';
        part.glyph.style.opacity = '';
      }
      if (line) line.style.transform = '';
      if (resolveFinish) resolveFinish();
    }

    function onVisibility() {
      // A hidden page throttles timers, so a finishing loader must not wait for them.
      if (document.hidden && finishing) settle();
    }

    function tick() {
      const now = performance.now();
      const delta = Math.min(0.25, (now - last) / 1000);
      last = now;
      target = Math.max(target, clamp(progress(now)));
      shown += (target - shown) * (1 - Math.exp(-delta / FOLLOW_SECONDS));
      if (line) line.style.transform = `scaleX(${shown.toFixed(4)})`;
    }

    function assemble() {
      if (settled) return;
      window.clearInterval(tickTimer);
      mark.classList.add('rl-forming');
      if (line) line.style.transform = 'scaleX(1)';
      parts.forEach((part, index) => land(part, index * LAND_STEP_MS));
      const wait = (parts.length - 1) * LAND_STEP_MS + LAND_MS + (align ? HOLD_MS : 30);
      finishTimer = window.setTimeout(settle, wait);
    }

    measure();
    if (line) line.style.transform = 'scaleX(0)';
    void mark.offsetWidth;
    mark.classList.add('rl-active');
    window.addEventListener('resize', measure, {passive: true});
    document.addEventListener('visibilitychange', onVisibility);
    tickTimer = window.setInterval(tick, TICK_MS);

    return {
      settle,
      finish() {
        if (settled || document.hidden) {
          settle();
          return Promise.resolve();
        }
        const done = new Promise(resolve => {
          const previous = resolveFinish;
          resolveFinish = () => {
            if (previous) previous();
            resolve();
          };
        });
        if (finishing) return done;
        finishing = true;
        // The page entrance lands on the next exact formation; quick tasks land at once.
        const now = document.timeline.currentTime ?? performance.now();
        const untilFormation = align ? cycle - ((now - startTime) % cycle) : 0;
        finishTimer = window.setTimeout(assemble, untilFormation);
        return done;
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
