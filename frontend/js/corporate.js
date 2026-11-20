'use strict';

(() => {
  // Keep shared links to the former single-page site useful.
  const legacySections = new Map([
    ['#evaluacion', '/contacto#evaluacion'],
    ['#privacidad', '/contacto#privacidad'],
    ['#proceso', '/proceso'],
    ['#preguntas', '/preguntas']
  ]);

  function redirectLegacySection() {
    if (window.location.pathname !== '/captacion') return;
    const target = legacySections.get(window.location.hash);
    if (!target) return;

    const destination = new URL(target, window.location.origin);
    destination.search = window.location.search;
    window.location.replace(destination.href);
  }

  window.addEventListener('hashchange', redirectLegacySection);
  redirectLegacySection();
})();
