'use strict';

(() => {
  const toggle = document.querySelector('#public-menu-toggle');
  const nav = document.querySelector('#public-nav');
  if (!toggle || !nav) return;

  function setMenuOpen(open, restoreFocus = false) {
    nav.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Cerrar menú' : 'Abrir menú');
    if (restoreFocus) toggle.focus();
  }

  toggle.addEventListener('click', () => {
    setMenuOpen(toggle.getAttribute('aria-expanded') !== 'true');
  });

  nav.addEventListener('click', event => {
    if (event.target.closest('a, [data-open-chat]')) setMenuOpen(false);
  });

  document.addEventListener('click', event => {
    if (toggle.getAttribute('aria-expanded') === 'true'
      && !nav.contains(event.target)
      && !toggle.contains(event.target)) {
      setMenuOpen(false);
    }
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
      setMenuOpen(false, true);
    }
  });

  window.addEventListener('resize', () => {
    if (window.matchMedia('(min-width: 1241px)').matches) setMenuOpen(false);
  });
})();
