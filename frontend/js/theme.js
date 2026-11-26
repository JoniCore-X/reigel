// Modo claro/oscuro de /app e /ia. Se carga en <head> sin defer para aplicar el
// tema antes de pintar. Preferencia guardada en este navegador; sin ella, la del
// sistema. El interruptor (Uiverse, Galahhad) es una casilla .ui-theme-switch__checkbox.
(() => {
  'use strict';
  const KEY = 'reigel-theme';
  const root = document.documentElement;
  const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function stored() {
    try {
      const value = localStorage.getItem(KEY);
      return value === 'dark' || value === 'light' ? value : null;
    } catch { return null; }
  }

  function apply(theme) {
    root.dataset.theme = theme;
    document.querySelectorAll('.ui-theme-switch__checkbox').forEach(box => { box.checked = theme === 'dark'; });
  }

  apply(stored() || (media && media.matches ? 'dark' : 'light'));
  media?.addEventListener?.('change', event => { if (!stored()) apply(event.matches ? 'dark' : 'light'); });
  document.addEventListener('DOMContentLoaded', () => apply(root.dataset.theme));
  document.addEventListener('change', event => {
    const box = event.target instanceof Element ? event.target.closest('.ui-theme-switch__checkbox') : null;
    if (!box) return;
    const theme = box.checked ? 'dark' : 'light';
    try { localStorage.setItem(KEY, theme); } catch { /* sin almacenamiento: vale para esta visita */ }
    apply(theme);
  });
})();
