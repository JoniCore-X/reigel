'use strict';

// Profundidad 3D de /captacion. Solo decora: sin este archivo la página queda
// plana y completa. No toca el transform de .tx-r, .tx-cta ni de la foto del
// hero, que pertenecen a tesla-experience.js; ahí usa la propiedad `translate`.
(() => {
  const homeImage = document.querySelector('.corp-home-photo img');
  const phoneImage = document.querySelector('.corp-energy-phone img');
  const hero = document.querySelector('.tx-hero');
  const stage = document.querySelector('.tx-surface-stage');
  const diagram = document.querySelector('.tx-z-figure svg');
  const cards = [...document.querySelectorAll('.corp-directory-item')];
  const roofImage = document.querySelector('.corp-roof-photo img');
  if (!homeImage && !phoneImage && !hero && !stage && !diagram && !cards.length && !roofImage) return;
  if (!('IntersectionObserver' in window)) return;

  const root = document.documentElement;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  const wide = window.matchMedia('(min-width: 821px)');
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const SETTLED = 0.002;

  const actors = [];
  let frame = 0;
  let lastTime = 0;
  let scrollDirty = true;

  const enabled = () => !reduced.matches && document.visibilityState === 'visible';

  function decorate(tag, className, parent) {
    const node = document.createElement(tag);
    node.className = className;
    node.setAttribute('aria-hidden', 'true');
    parent.append(node);
    return node;
  }

  // Envuelve la imagen en una lámina con cortes de grosor; no cambia su contenido.
  function buildPlate(image, edges, withGlare) {
    const plate = document.createElement('span');
    plate.className = 'd3-plate';
    image.before(plate);
    plate.append(image);
    for (let index = edges; index >= 1; index -= 1) {
      decorate('i', 'd3-edge', plate).style.setProperty('--d3-i', String(index));
    }
    plate.append(image);
    const glare = withGlare ? decorate('span', 'd3-glare', plate) : null;
    return { plate, glare, shine: glare ? decorate('b', '', glare) : null };
  }

  function addActor(config) {
    const actor = {
      x: 0, y: 0, p: config.rest ?? 0, h: 0,
      tx: 0, ty: 0, tp: config.rest ?? 0, th: 0,
      visible: false, box: null, animating: false,
      ...config,
    };
    actors.push(actor);
    if (actor.region && actor.pointer !== false) bindPointer(actor);
    observer.observe(actor.watch);
    return actor;
  }

  function bindPointer(actor) {
    actor.region.addEventListener('pointerenter', () => { actor.box = null; }, { passive: true });
    actor.region.addEventListener('pointermove', event => {
      if (event.pointerType === 'touch' || !finePointer.matches || !enabled()) return;
      actor.box ||= actor.region.getBoundingClientRect();
      actor.tx = clamp((event.clientX - actor.box.left) / actor.box.width - 0.5, -0.5, 0.5) * 2;
      actor.ty = clamp((event.clientY - actor.box.top) / actor.box.height - 0.5, -0.5, 0.5) * 2;
      actor.th = 1;
      request();
    }, { passive: true });
    actor.region.addEventListener('pointerleave', () => {
      actor.tx = 0;
      actor.ty = 0;
      actor.th = 0;
      request();
    }, { passive: true });
  }

  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      actors.forEach(actor => {
        if (actor.watch !== entry.target) return;
        actor.visible = entry.isIntersecting;
        if (!actor.visible) setAnimating(actor, false);
        // Al entrar parte de su posición real, sin un salto desde la anterior.
        else if (actor.measure) actor.p = actor.tp = actor.measure(window.innerHeight);
      });
    });
    scrollDirty = true;
    request();
  }, { rootMargin: '10% 0px' });

  function request() {
    if (!frame && enabled() && actors.some(actor => actor.visible)) {
      frame = window.requestAnimationFrame(tick);
    }
  }

  function tick(time) {
    frame = 0;
    if (!enabled()) return;
    const elapsed = lastTime ? Math.min(64, time - lastTime) : 16.67;
    lastTime = time;
    const ease = 1 - Math.pow(0.86, elapsed / 16.67);
    const height = window.innerHeight;
    let moving = false;

    actors.forEach(actor => {
      if (!actor.visible) {
        setAnimating(actor, false);
        return;
      }
      if (scrollDirty && actor.measure) {
        actor.box = actor.region ? null : actor.box;
        actor.tp = actor.measure(height);
      }
      actor.x += (actor.tx - actor.x) * ease;
      actor.y += (actor.ty - actor.y) * ease;
      actor.p += (actor.tp - actor.p) * ease;
      actor.h += (actor.th - actor.h) * ease;
      const active = [actor.tx - actor.x, actor.ty - actor.y, actor.tp - actor.p, actor.th - actor.h]
        .some(delta => Math.abs(delta) > SETTLED);
      if (!active) {
        actor.x = actor.tx;
        actor.y = actor.ty;
        actor.p = actor.tp;
        actor.h = actor.th;
      }
      actor.apply(actor);
      setAnimating(actor, active);
      moving ||= active;
    });

    scrollDirty = false;
    if (moving) request();
    else lastTime = 0;
  }

  function setAnimating(actor, value) {
    if (actor.animating === value) return;
    actor.animating = value;
    (actor.layers || []).forEach(layer => { layer.style.willChange = value ? 'transform' : ''; });
  }

  function clearActors() {
    actors.forEach(actor => {
      Object.assign(actor, { x: 0, y: 0, h: 0, tx: 0, ty: 0, th: 0, p: actor.rest ?? 0, tp: actor.rest ?? 0 });
      setAnimating(actor, false);
      actor.clear();
    });
  }

  // Posición del centro respecto al del viewport, de -1 a 1.
  function centerOffset(element) {
    return height => {
      const box = element.getBoundingClientRect();
      return clamp((box.top + box.height / 2 - height / 2) / height, -1, 1);
    };
  }

  // Recorta la foto en su propio plano para inclinarla sin invadir lo demás.
  function buildClip(image) {
    const clip = document.createElement('span');
    clip.className = 'd3-clip';
    image.before(clip);
    clip.append(image);
    return clip;
  }

  function setupHome() {
    if (!homeImage) return;
    const figure = homeImage.closest('figure');
    const { plate, glare, shine } = buildPlate(homeImage, 12, true);
    const caption = figure.querySelector('figcaption');
    let size = null;
    window.addEventListener('resize', () => { size = null; }, { passive: true });

    // Distancia del borde izquierdo visible de la foto, sin contar el puntero.
    function captionShift(turn, lift) {
      size ||= { width: plate.offsetWidth, height: plate.offsetHeight };
      const matrix = new DOMMatrix();
      matrix.m34 = -1 / 1100;
      matrix.rotateAxisAngleSelf(1, 0, 0, lift);
      matrix.rotateAxisAngleSelf(0, 1, 0, turn);
      const corner = matrix.transformPoint(new DOMPoint(-size.width, size.height / 2, 0, 1));
      return size.width + corner.x / corner.w;
    }

    addActor({
      watch: figure,
      region: figure.closest('.corp-home'),
      layers: [plate, shine],
      measure: centerOffset(figure),
      apply(actor) {
        // Ángulo de reposo: el grosor se ve sin puntero, también en teléfono.
        const restTurn = (wide.matches ? -8.5 : -11) - actor.p * 3;
        const restLift = 2.5 - actor.p * 2.5;
        const turn = restTurn + actor.x * 4;
        const lift = restLift - actor.y * 3;
        plate.style.transform = `perspective(1100px) rotateX(${lift.toFixed(2)}deg) rotateY(${turn.toFixed(2)}deg)`;
        if (caption) caption.style.translate = `${captionShift(restTurn, restLift).toFixed(1)}px 0`;
        shine.style.transform = `translate3d(${(actor.x * 26).toFixed(1)}%, ${(actor.y * 26).toFixed(1)}%, 0)`;
        glare.style.opacity = actor.h.toFixed(3);
        figure.style.setProperty('--d3-sun', `${(-actor.x * 12).toFixed(1)}px ${(-actor.y * 8 + actor.p * 16).toFixed(1)}px`);
      },
      clear() {
        plate.style.transform = '';
        if (caption) caption.style.translate = '';
        shine.style.transform = '';
        glare.style.opacity = '';
        figure.style.removeProperty('--d3-sun');
      },
    });
  }

  function setupPhone() {
    if (!phoneImage) return;
    const figure = phoneImage.closest('figure');
    const { plate } = buildPlate(phoneImage, 8, false);
    addActor({
      watch: figure,
      region: figure.closest('.corp-energy-view'),
      layers: [plate],
      measure(height) {
        const box = figure.getBoundingClientRect();
        return clamp((box.top + box.height / 2 - height / 2) / height, -1, 1);
      },
      apply(actor) {
        const turn = (wide.matches ? -12 : -8) + actor.x * 5 + actor.p * 5;
        const lift = 3 - actor.y * 3 + actor.p * 2;
        plate.style.transform = `perspective(1000px) rotateX(${lift.toFixed(2)}deg) rotateY(${turn.toFixed(2)}deg)`;
      },
      clear() { plate.style.transform = ''; },
    });
  }

  function setupHero() {
    if (!hero) return;
    const image = hero.querySelector('.tx-hero-media img');
    const figure = hero.querySelector('.tx-figure');
    if (!image || !figure) return;
    buildClip(image);
    addActor({
      watch: hero,
      region: hero,
      layers: [image, figure],
      measure: centerOffset(hero),
      apply(actor) {
        // La foto queda detrás y gira; «420 W» avanza sin girar; el texto no se mueve.
        const large = wide.matches;
        const rx = large ? 1.5 + actor.p * 2.5 - actor.y : 1.5 + actor.p * 3 - actor.y * 0.5;
        const ry = large ? -2.5 + actor.x * 1.8 : -2.5 + actor.x;
        const angle = Math.hypot(rx, ry);
        const shiftX = large ? -actor.x * 8 : -actor.x * 3;
        const shiftY = large ? actor.p * 5 - actor.y * 3 : actor.p * 3 - actor.y * 1.5;
        image.style.translate = `${shiftX.toFixed(1)}px ${shiftY.toFixed(1)}px -24px`;
        image.style.rotate = angle > 0.01 ? `${rx.toFixed(3)} ${ry.toFixed(3)} 0 ${angle.toFixed(2)}deg` : 'none';
        // Escala mínima para que la foto cubra su plano en cualquier ángulo.
        image.style.scale = (1.09 + window.innerWidth * 0.000045).toFixed(4);
        const forward = (wide.matches ? 44 : 18) * (1 - Math.abs(actor.p) * 0.6);
        figure.style.translate = `${(actor.x * 10).toFixed(1)}px ${(actor.y * 5).toFixed(1)}px ${forward.toFixed(1)}px`;
      },
      clear() {
        image.style.translate = '';
        image.style.rotate = '';
        image.style.scale = '';
        figure.style.translate = '';
      },
    });
  }

  function setupSurface() {
    if (!stage) return;
    const plane = stage.querySelector('.tx-frame');
    const marks = stage.querySelector('.tx-marks');
    if (!plane) return;
    addActor({
      watch: stage,
      layers: [plane],
      rest: 1,
      measure(height) {
        const box = stage.getBoundingClientRect();
        return clamp((height * 0.95 - box.top) / (height * 0.45), 0, 1);
      },
      apply(actor) {
        const away = 1 - actor.p;
        const tilt = away * (wide.matches ? 10 : 6);
        plane.style.transform = away < 0.001 ? '' : `perspective(1400px) rotateX(${tilt.toFixed(2)}deg) scale(${(1 - away * 0.05).toFixed(4)})`;
        // Las etiquetas aparecen cuando la foto ya está frontal y siguen alineadas.
        if (marks) marks.style.opacity = wide.matches ? clamp((actor.p - 0.82) / 0.18, 0, 1).toFixed(3) : '';
      },
      clear() {
        plane.style.transform = '';
        if (marks) marks.style.opacity = '';
      },
    });
  }

  function setupZones() {
    if (!diagram) return;
    const slab = document.createElement('span');
    slab.className = 'd3-slab';
    diagram.before(slab);
    decorate('i', 'd3-ground', slab);
    slab.append(diagram);
    // Grosor en las coordenadas del SVG: una sola silueta, sin uniones entre caras.
    const NS = 'http://www.w3.org/2000/svg';
    const extrusion = document.createElementNS(NS, 'g');
    extrusion.setAttribute('class', 'd3-extrude');
    [['d3-extrude-body', 'M436 24L448 39V591H76L64 576H436Z'], ['d3-extrude-side', 'M436 24L448 39V591L436 576Z']].forEach(([name, shape]) => {
      const path = document.createElementNS(NS, 'path');
      path.setAttribute('class', name);
      path.setAttribute('d', shape);
      extrusion.append(path);
    });
    diagram.querySelector('defs').after(extrusion);
    new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) slab.classList.add('d3-iso');
    }, { threshold: 0.35 }).observe(slab.parentElement);
  }

  function setupCards() {
    cards.forEach(card => {
      addActor({
        watch: card,
        region: card,
        layers: [card],
        apply(actor) {
          card.style.transform = actor.x || actor.y
            ? `perspective(900px) rotateX(${(-actor.y * 1.4).toFixed(2)}deg) rotateY(${(actor.x * 1.8).toFixed(2)}deg)`
            : '';
        },
        clear() { card.style.transform = ''; },
      });
    });
  }

  function setupRoof() {
    if (!roofImage) return;
    const section = roofImage.closest('.corp-roof-cta');
    buildClip(roofImage);
    addActor({
      watch: section,
      layers: [roofImage],
      measure: centerOffset(section),
      apply(actor) {
        const large = wide.matches;
        const tilt = large ? 2 + actor.p * 4 : 1.5 + actor.p * 3.5;
        const shift = actor.p * (large ? 5 : 3);
        const cover = (1.1 + window.innerWidth * 0.00004).toFixed(4);
        roofImage.style.transform = `translate3d(0, ${shift.toFixed(1)}px, -28px) rotateX(${tilt.toFixed(2)}deg) rotateY(-2.5deg) scale(${cover})`;
      },
      clear() { roofImage.style.transform = ''; },
    });
  }

  function syncMode() {
    root.classList.toggle('d3-live', !reduced.matches);
    if (!enabled()) {
      if (frame) window.cancelAnimationFrame(frame);
      frame = 0;
      lastTime = 0;
      clearActors();
      return;
    }
    scrollDirty = true;
    request();
  }

  function markScroll() {
    scrollDirty = true;
    request();
  }

  setupHome();
  setupPhone();
  setupHero();
  setupSurface();
  setupZones();
  setupCards();
  setupRoof();
  syncMode();

  window.addEventListener('scroll', markScroll, { passive: true });
  window.addEventListener('resize', () => {
    actors.forEach(actor => { actor.box = null; });
    markScroll();
  }, { passive: true });
  document.addEventListener('visibilitychange', syncMode);
  reduced.addEventListener?.('change', syncMode);
  wide.addEventListener?.('change', markScroll);
})();
