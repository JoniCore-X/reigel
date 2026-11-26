'use strict';

// Movimiento de la sección de la placa en /captacion. El contenido y el comparador
// funcionan sin este archivo: aquí solo se añaden revelados, parallax y la sombra.
(() => {
  const root = document.querySelector('.tx');
  if (!root) return;

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  const wideHero = window.matchMedia('(min-width: 821px)');
  const reveals = [...root.querySelectorAll('[data-tx-reveal]')];
  const hero = root.querySelector('.tx-hero');
  const heroImage = root.querySelector('.tx-hero-media img');
  const zones = root.querySelector('.tx-z');
  const diagram = root.querySelector('.tx-z-figure svg');
  const pauseButton = root.querySelector('.tx-z-pause');

  // Recorrido de la sombra (columna, fila): cruza de un bloque grande al otro.
  const PATH = [[1, 3], [1, 4], [2, 4], [2, 3], [2, 2], [1, 2]];
  const STEP_MS = 1700;
  const PARALLAX_PX = 16;

  let revealObserver = null;
  let step = 0;
  let timer = 0;
  let zonesInView = false;
  let paused = false;
  let heroInView = false;
  let frame = 0;

  function showEverything() {
    revealObserver?.disconnect();
    revealObserver = null;
    root.classList.remove('tx-armed');
    reveals.forEach(item => item.classList.add('is-in'));
  }

  function armReveals() {
    // Una pestaña oculta no entrega observaciones: ahí el contenido queda visible.
    if (reduced.matches || document.visibilityState !== 'visible' || !('IntersectionObserver' in window)) {
      showEverything();
      return;
    }
    root.classList.add('tx-armed');
    revealObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-in');
        revealObserver?.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    reveals.forEach(item => revealObserver.observe(item));
  }

  function placeShadow(index) {
    const [column, row] = PATH[index];
    diagram.style.setProperty('--c', column);
    diagram.style.setProperty('--r', row);
    diagram.style.setProperty('--z', Math.floor(row / 3));
  }

  function stopShadow() {
    window.clearInterval(timer);
    timer = 0;
  }

  function syncShadow() {
    const shouldRun = zonesInView && !paused && !reduced.matches && document.visibilityState === 'visible';
    if (!shouldRun) {
      stopShadow();
      return;
    }
    if (timer) return;
    timer = window.setInterval(() => {
      step = (step + 1) % PATH.length;
      placeShadow(step);
    }, STEP_MS);
  }

  function syncPauseButton() {
    if (!pauseButton) return;
    pauseButton.hidden = reduced.matches;
    pauseButton.textContent = paused ? 'Mover la sombra' : 'Pausar la sombra';
    pauseButton.setAttribute('aria-pressed', String(paused));
  }

  function renderParallax() {
    frame = 0;
    if (!heroInView || !wideHero.matches || reduced.matches) return;
    const box = hero.getBoundingClientRect();
    const span = window.innerHeight + box.height;
    const progress = span > 0 ? (window.innerHeight - box.top) / span : 0.5;
    const offset = (Math.min(1, Math.max(0, progress)) - 0.5) * 2 * PARALLAX_PX;
    heroImage.style.setProperty('--tx-py', `${offset.toFixed(1)}px`);
  }

  function requestParallax() {
    if (!frame && heroInView) frame = window.requestAnimationFrame(renderParallax);
  }

  function syncMotionClass() {
    root.classList.toggle('tx-motion', !reduced.matches);
    if (reduced.matches) heroImage?.style.removeProperty('--tx-py');
  }

  function bindMagnetic() {
    root.querySelectorAll('.tx-cta').forEach(button => {
      button.addEventListener('pointermove', event => {
        if (!finePointer.matches || reduced.matches) return;
        const box = button.getBoundingClientRect();
        const x = ((event.clientX - box.left) / box.width - 0.5) * 6;
        const y = ((event.clientY - box.top) / box.height - 0.5) * 4;
        button.style.setProperty('--tx-mx', `${x.toFixed(1)}px`);
        button.style.setProperty('--tx-my', `${y.toFixed(1)}px`);
      });
      button.addEventListener('pointerleave', () => {
        button.style.removeProperty('--tx-mx');
        button.style.removeProperty('--tx-my');
      });
    });
  }

  syncMotionClass();
  armReveals();
  bindMagnetic();

  if (diagram) placeShadow(step);
  syncPauseButton();

  pauseButton?.addEventListener('click', () => {
    paused = !paused;
    syncPauseButton();
    syncShadow();
  });

  if ('IntersectionObserver' in window) {
    if (zones && diagram) {
      new IntersectionObserver(entries => {
        zonesInView = entries[entries.length - 1].isIntersecting;
        syncShadow();
      }, { threshold: 0.2 }).observe(zones);
    }
    if (hero && heroImage) {
      new IntersectionObserver(entries => {
        heroInView = entries[entries.length - 1].isIntersecting;
        requestParallax();
      }).observe(hero);
      window.addEventListener('scroll', requestParallax, { passive: true });
      window.addEventListener('resize', requestParallax, { passive: true });
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') showEverything();
    syncShadow();
  });

  reduced.addEventListener?.('change', () => {
    syncMotionClass();
    if (reduced.matches) showEverything();
    syncPauseButton();
    syncShadow();
  });
})();
