'use strict';

(() => {
  const selector = document.querySelector('.hero-intents');
  const launcher = document.querySelector('.chat-launcher');
  if (!selector || !launcher || !('IntersectionObserver' in window)) return;

  const compact = window.matchMedia('(max-width: 600px)');
  let selectorVisible = false;

  function updateLauncher() {
    document.body.classList.toggle('intent-selector-visible', compact.matches && selectorVisible);
  }

  const observer = new IntersectionObserver(entries => {
    selectorVisible = entries.some(entry => entry.isIntersecting);
    updateLauncher();
  }, {rootMargin: '0px 0px -96px 0px'});

  observer.observe(selector);
  compact.addEventListener('change', updateLauncher);
})();
