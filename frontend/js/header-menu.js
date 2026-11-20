'use strict';

(() => {
  const toggle = document.querySelector('#public-menu-toggle');
  const nav = document.querySelector('#public-nav');
  if (!toggle || !nav) return;

  const header = toggle.closest('.public-header');
  const dialog = nav.querySelector('.mobile-menu-dialog');
  const closeButton = nav.querySelector('[data-close-menu]');
  const backdrop = document.querySelector('#public-menu-backdrop');
  const mobileMenu = window.matchMedia('(max-width: 600px)');
  const savedBackground = new Map();

  function isOpen() {
    return toggle.getAttribute('aria-expanded') === 'true';
  }

  function isModalOpen() {
    return isOpen() && mobileMenu.matches;
  }

  function getFocusable(container) {
    if (!container) return [];
    return [...container.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )].filter(element => element.getClientRects().length > 0 && !element.closest('[inert], [aria-hidden="true"]'));
  }

  function backgroundTargets() {
    const targets = [...document.body.children].filter(element => element !== header && element !== backdrop);
    if (header) targets.push(...[...header.children].filter(element => element !== nav));
    return [...new Set(targets)];
  }

  function setBackgroundInert(inert) {
    if (inert) {
      for (const element of backgroundTargets()) {
        if (!savedBackground.has(element)) {
          savedBackground.set(element, {
            inert: element.inert,
            ariaHidden: element.getAttribute('aria-hidden')
          });
        }
        element.inert = true;
        element.setAttribute('aria-hidden', 'true');
      }
      return;
    }

    for (const [element, state] of savedBackground) {
      element.inert = state.inert;
      if (state.ariaHidden === null) element.removeAttribute('aria-hidden');
      else element.setAttribute('aria-hidden', state.ariaHidden);
    }
    savedBackground.clear();
  }

  function setMenuOpen(open, restoreFocus = false) {
    nav.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Cerrar menú' : 'Abrir menú');
    closeButton?.setAttribute('aria-expanded', String(open));

    const modal = open && mobileMenu.matches;
    document.body.classList.toggle('public-menu-open', modal);
    if (backdrop) backdrop.hidden = !modal;
    setBackgroundInert(modal);

    if (open) {
      requestAnimationFrame(() => {
        if (!isOpen()) return;
        if (mobileMenu.matches) (closeButton || dialog)?.focus({ preventScroll: true });
        else getFocusable(nav)[0]?.focus({ preventScroll: true });
      });
    } else if (restoreFocus) {
      requestAnimationFrame(() => toggle.focus({ preventScroll: true }));
    }
  }

  toggle.addEventListener('click', () => {
    setMenuOpen(!isOpen());
  });

  closeButton?.addEventListener('click', () => setMenuOpen(false, true));
  backdrop?.addEventListener('click', () => setMenuOpen(false, true));

  // Close before the chat trigger runs so chat.js records the menu toggle as
  // its return-focus target rather than a button that is about to be hidden.
  nav.addEventListener('click', event => {
    if (!isOpen()) return;
    const action = event.target.closest('a[href], [data-open-chat]');
    if (action && nav.contains(action)) setMenuOpen(false, true);
  }, true);

  document.addEventListener('click', event => {
    if (!isOpen() || nav.contains(event.target) || toggle.contains(event.target) || backdrop?.contains(event.target)) return;
    setMenuOpen(false, isModalOpen());
  });

  document.addEventListener('keydown', event => {
    if (!isOpen()) return;

    if (event.key === 'Escape') {
      event.preventDefault();
      setMenuOpen(false, true);
      return;
    }

    if (event.key !== 'Tab' || !isModalOpen()) return;
    const focusable = getFocusable(dialog);
    if (!focusable.length) {
      event.preventDefault();
      dialog?.focus({ preventScroll: true });
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
      event.preventDefault();
      first.focus();
    }
  });

  window.addEventListener('resize', () => {
    if (document.body.classList.contains('public-menu-open') && !mobileMenu.matches) {
      setMenuOpen(false, false);
    } else if (window.matchMedia('(min-width: 1241px)').matches) {
      setMenuOpen(false, false);
    }
  });
})();
