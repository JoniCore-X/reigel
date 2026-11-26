'use strict';

// Tesla Panel Mount Flat. Solo mejora: sin este archivo, las piezas y los
// desplegables nativos siguen visibles y utilizables.
(() => {
  const page = document.querySelector('[data-pm-page]');
  if (!page) return;

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const header = document.querySelector('.public-header');
  const syncHeader = () => page.style.setProperty('--pm-head', `${header ? header.offsetHeight : 0}px`);
  syncHeader();
  window.addEventListener('resize', syncHeader, { passive: true });

  /* ---------- Las 18 piezas ---------- */
  function setupExplorer() {
    const root = page.querySelector('[data-pm-explorer]');
    if (!root) return;
    const parts = [...root.querySelectorAll('.pm-part')];
    const groups = [...root.querySelectorAll('.pm-group')];
    const filters = [...root.querySelectorAll('[data-filter]')];
    const count = root.querySelector('[data-pm-count]');
    const name = root.querySelector('[data-pm-name]');
    let current = null;

    const visible = () => parts.filter(part => !part.closest('.pm-group').hidden);

    // Un solo número por pieza: el mismo de la escena.
    function paint() {
      if (current && visible().includes(current)) {
        count.textContent = `${current.dataset.number} / 18`;
        name.textContent = current.querySelector('.pm-part-name').textContent;
      } else {
        count.textContent = `${visible().length} piezas`;
        name.textContent = '';
      }
    }

    // Cerrar otra pieza no debe mover la que se acaba de abrir.
    function closeOthers(keep) {
      const anchor = keep.getBoundingClientRect().top;
      parts.forEach(part => {
        if (part !== keep) part.querySelector('details').open = false;
      });
      const shift = keep.getBoundingClientRect().top - anchor;
      if (shift) window.scrollBy({ top: shift, behavior: 'instant' });
    }

    parts.forEach(part => {
      part.querySelector('details').addEventListener('toggle', event => {
        if (!event.target.open) return;
        closeOthers(part);
        current = part;
        paint();
      });
    });

    filters.forEach(button => button.addEventListener('click', () => {
      const key = button.dataset.filter;
      filters.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      groups.forEach(group => {
        group.hidden = key !== 'all' && group.dataset.group !== key;
        if (group.hidden) group.querySelectorAll('details').forEach(details => { details.open = false; });
      });
      if (current && !visible().includes(current)) current = null;
      paint();
    }));

    root.querySelector('[data-pm-controls]').hidden = false;
    paint();
  }

  /* ---------- Montaje ligado a la posición de desplazamiento ---------- */
  // El estado es una función pura del scroll: bajar monta y subir desmonta.
  function setupScene() {
    const scene = page.querySelector('[data-pm-scene]');
    if (!scene || !('IntersectionObserver' in window)) return;
    const track = scene.querySelector('[data-pm-track]');
    const stage = scene.querySelector('[data-pm-stage]');
    const board = scene.querySelector('[data-pm-board]');
    const present = scene.querySelector('[data-pm-present]');
    const final = scene.querySelector('[data-pm-final]');
    const leader = scene.querySelector('.pm-leader path');
    const dot = scene.querySelector('.pm-leader circle');
    const heads = [...scene.querySelectorAll('.pm-ch-head')];
    const bars = [...scene.querySelectorAll('[data-prog] b')];
    const progressBar = scene.querySelector('.pm-prog');
    const done = scene.querySelector('[data-pm-done]');
    const tiers = [...scene.querySelectorAll('.pm-tier')];
    const tierOf = chapter => tiers.find(tier => Number(tier.dataset.tier) === chapter);
    const sizes = [...scene.querySelectorAll('.pm-ch')].map(chapter => chapter.querySelectorAll('.pm-seq-item').length);
    const items = [...scene.querySelectorAll('.pm-seq-item')].map(node => ({
      node,
      fig: node.querySelector('.pm-seq-fig'),
      label: node.querySelector('.pm-seq-label'),
      caption: node.querySelector('.pm-seq-fig figcaption'),
      captionStyle: '',
      figStyle: '',
      labelStyle: '',
    }));
    const tall = window.matchMedia('(min-height: 500px)');
    const compact = window.matchMedia('(max-width: 860px)');
    const TOTAL = items.length;
    const START = 0.25;
    const GAPS = [0.6, 0.6, 0.5];
    const CONVERGE = 1.1;
    const REVEAL = 0.9;
    const HOLD = 0.35;
    const UNITS = TOTAL + GAPS.reduce((sum, gap) => sum + gap, 0) + CONVERGE + REVEAL + HOLD;
    const smooth = value => value * value * (3 - 2 * value);
    const unit = value => Math.min(1, Math.max(0, value));
    const mix = (from, to, amount) => from + (to - from) * amount;
    const px = value => value.toFixed(2);
    const firsts = sizes.map((_, chapter) => sizes.slice(0, chapter).reduce((sum, size) => sum + size, 0));
    const chapterOf = index => sizes.findIndex((size, chapter) => index < firsts[chapter] + size);
    let live = false;
    let inView = false;
    let frame = 0;
    let geometry = [];
    let axis = { x: 0, y: 0 };
    let drawn = -1;

    // Avance de piezas, compactación por capítulo, convergencia y revelado.
    function decode(position) {
      const state = { advance: 0, compact: [0, 0, 0], converge: 0, reveal: 0 };
      let rest = position;
      for (let chapter = 0; chapter < sizes.length; chapter += 1) {
        const take = Math.min(rest, sizes[chapter]);
        state.advance += Math.max(0, take);
        rest -= sizes[chapter];
        if (rest <= 0) return state;
        state.compact[chapter] = unit(rest / GAPS[chapter]);
        rest -= GAPS[chapter];
        if (rest <= 0) return state;
      }
      state.converge = unit(rest / CONVERGE);
      // La foto empieza a aparecer mientras las piezas se disuelven: no hay tramo vacío.
      state.reveal = unit((rest - CONVERGE * 0.55) / REVEAL);
      return state;
    }

    const offsetIn = (node, ancestor) => {
      let x = 0;
      let y = 0;
      for (let current = node; current && current !== ancestor; current = current.offsetParent) {
        x += current.offsetLeft;
        y += current.offsetTop;
      }
      return { x, y };
    };

    function measure() {
      if (!live) return;
      syncHeader();
      stage.style.setProperty('--pm-fig-h', `${Math.max(70, present.offsetHeight - 18)}px`);
      const boardBox = offsetIn(board, stage);
      axis = { x: boardBox.x + board.offsetWidth / 2, y: boardBox.y + board.offsetHeight / 2 };
      const presentW = present.offsetWidth;
      geometry = items.map((item, index) => {
        const chapter = chapterOf(index);
        const tier = tierOf(chapter);
        const tierBox = offsetIn(tier, stage);
        const tierW = tier.offsetWidth;
        const tierH = tier.offsetHeight;
        const n = sizes[chapter];
        const k = index - firsts[chapter];
        const cell = (tierW - (compact.matches ? tier.firstElementChild.offsetWidth + 6 : 0)) / n;
        const w = item.fig.offsetWidth;
        const h = item.fig.offsetHeight;
        const cx = item.fig.offsetLeft + w / 2;
        const cy = item.fig.offsetTop + h / 2;
        const scale = Math.min(Math.min(cell * 1.75, tierW * 0.3) / w, tierH * (compact.matches ? 0.47 : 0.42) / h, 1);
        // Las piezas quedan dentro de su nivel: el primer y el último hueco tocan el borde, no lo cruzan.
        const half = (w * scale) / 2 + 2;
        // En teléfono el nombre del nivel va en vertical a la izquierda; las piezas empiezan después.
        const gutter = compact.matches ? tier.firstElementChild.offsetWidth + 6 : 0;
        const slotX = tierBox.x + gutter + half + (tierW - gutter - 2 * half) * (n > 1 ? k / (n - 1) : 0.5);
        const slotY = tierBox.y + tierH * (compact.matches ? (k % 2 ? 0.73 : 0.29) : (k % 2 ? 0.72 : 0.4));
        const labelBox = offsetIn(item.label, stage);
        const startY = cy + h / 2 + 6;
        const endY = labelBox.y + 6;
        const midY = startY + Math.max(4, (endY - startY) / 2);
        return {
          cx,
          cy,
          slotX,
          slotY,
          scale,
          enterX: presentW * 0.55,
          path: `M${px(cx)} ${px(startY)}V${px(midY)}H${px(labelBox.x + 8)}V${px(endY)}`,
          dotX: cx,
          dotY: startY,
        };
      });
      drawn = -1;
    }

    function render() {
      frame = 0;
      if (!live || !geometry.length) return;
      const box = track.getBoundingClientRect();
      const top = header ? header.offsetHeight : 0;
      const range = Math.max(1, box.height - stage.offsetHeight);
      const progress = unit((top - box.top) / range);
      const state = decode(START + progress * (UNITS - START));
      const { advance, converge, reveal } = state;
      const active = Math.min(TOTAL - 1, Math.floor(advance));
      const fade = 1 - smooth(unit((converge - 0.35) / 0.65));

      items.forEach((item, index) => {
        const t = unit(advance - index);
        const g = geometry[index];
        const chapter = chapterOf(index);
        const squeeze = 1 - 0.14 * smooth(state.compact[chapter]);
        let x = 0;
        let y = 0;
        let scale = 1;
        let opacity = 1;
        if (t < 0.2) {
          const e = smooth(t / 0.2);
          x = g.enterX * (1 - e);
          y = 6;
          scale = 0.9 + 0.1 * e;
          opacity = e;
        } else if (t < 0.58) {
          y = mix(6, -6, (t - 0.2) / 0.38);
        } else {
          const m = smooth((t - 0.58) / 0.42);
          const slotX = axis.x + (g.slotX - axis.x) * squeeze;
          x = (slotX - g.cx) * m;
          y = mix(-6, g.slotY - g.cy, m);
          scale = mix(1, g.scale, m);
        }
        if (converge > 0 && t >= 1) {
          // Converge por niveles, de arriba abajo, para que no se amontonen a la vez.
          const own = unit(converge * 1.6 - (sizes.length - 1 - chapter) * 0.3);
          const c = smooth(own);
          const restX = g.cx + x;
          const restY = g.cy + y;
          x = mix(restX, axis.x, c * 0.85) - g.cx;
          y = mix(restY, axis.y, c * 0.5) - g.cy;
          scale *= 1 - 0.25 * c;
          opacity = 1 - smooth(unit((own - 0.35) / 0.65));
        }
        if (item.caption) {
          const caption = (1 - smooth(unit((t - 0.58) / 0.2))).toFixed(3);
          if (caption !== item.captionStyle) {
            item.captionStyle = caption;
            item.caption.style.opacity = caption;
          }
        }
        const figStyle = `${px(x)}|${px(y)}|${scale.toFixed(4)}|${opacity.toFixed(3)}`;
        if (figStyle !== item.figStyle) {
          item.figStyle = figStyle;
          item.fig.style.transform = `translate3d(${px(x)}px, ${px(y)}px, 0) scale(${scale.toFixed(4)})`;
          item.fig.style.opacity = opacity.toFixed(3);
        }
        const shown = converge > 0 ? 0 : smooth(unit((t - 0.12) / 0.08)) * (1 - smooth(unit((t - 0.62) / 0.08)));
        const labelStyle = shown.toFixed(3);
        if (labelStyle !== item.labelStyle) {
          item.labelStyle = labelStyle;
          item.label.style.opacity = labelStyle;
          item.label.style.transform = `translateY(${px(8 * (1 - shown))}px)`;
        }
      });

      if (active !== drawn) {
        drawn = active;
        leader.setAttribute('d', geometry[active].path);
        dot.setAttribute('cx', px(geometry[active].dotX));
        dot.setAttribute('cy', px(geometry[active].dotY));
      }
      const local = unit(advance - active);
      const line = converge > 0 ? 0 : unit((local - 0.16) / 0.12) * (1 - unit((local - 0.56) / 0.06));
      leader.style.strokeDashoffset = (1 - line).toFixed(3);
      dot.style.opacity = line.toFixed(3);

      const current = converge > 0 ? -1 : chapterOf(active);
      heads.forEach((head, index) => head.classList.toggle('is-current', index === current));
      tiers.forEach(tier => tier.classList.toggle('is-current', Number(tier.dataset.tier) === current));
      bars.forEach((bar, index) => {
        bar.style.transform = `scaleX(${unit((advance - firsts[index]) / sizes[index]).toFixed(4)})`;
      });
      board.style.opacity = fade.toFixed(3);
      progressBar.style.opacity = fade.toFixed(3);
      done.style.opacity = (smooth(state.compact[sizes.length - 1]) * (1 - smooth(unit(converge / 0.4)))).toFixed(3);
      final.style.opacity = reveal.toFixed(3);
      final.style.transform = `scale(${(0.95 + 0.05 * smooth(reveal)).toFixed(4)})`;
      stage.dataset.pmStep = reveal > 0 ? 'final' : converge > 0 ? 'converge' : items[active].node.dataset.key;
    }

    const schedule = () => {
      if (!live) return;
      if (document.visibilityState !== 'visible') render();
      else if (inView && !frame) frame = window.requestAnimationFrame(render);
    };

    function enable() {
      if (live || reduced.matches || !tall.matches) return;
      live = true;
      scene.classList.add('is-live');
      measure();
      render();
    }

    function disable() {
      if (!live) return;
      if (frame) window.cancelAnimationFrame(frame);
      frame = 0;
      live = false;
      geometry = [];
      scene.classList.remove('is-live');
      stage.style.removeProperty('--pm-fig-h');
      delete stage.dataset.pmStep;
      items.forEach(item => {
        item.figStyle = '';
        item.labelStyle = '';
        item.captionStyle = '';
        if (item.caption) item.caption.style.removeProperty('opacity');
        ['transform', 'opacity'].forEach(name => {
          item.fig.style.removeProperty(name);
          item.label.style.removeProperty(name);
        });
      });
      [final, board, progressBar, done, ...bars].forEach(node => {
        node.style.removeProperty('transform');
        node.style.removeProperty('opacity');
      });
      [...heads, ...tiers].forEach(node => node.classList.remove('is-current'));
    }

    const remeasure = () => {
      measure();
      schedule();
    };
    const syncMode = () => {
      if (reduced.matches || !tall.matches) disable();
      else enable();
    };

    new IntersectionObserver(entries => {
      inView = entries.some(entry => entry.isIntersecting);
      schedule();
    }, { rootMargin: '10% 0px' }).observe(track);
    if ('ResizeObserver' in window) new ResizeObserver(remeasure).observe(stage);
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', remeasure, { passive: true });
    compact.addEventListener('change', remeasure);
    tall.addEventListener('change', syncMode);
    reduced.addEventListener('change', syncMode);
    document.addEventListener('visibilitychange', () => {
      if (live) render();
    });
    window.addEventListener('load', remeasure, { once: true });
    syncMode();
  }

  setupExplorer();
  setupScene();
})();
