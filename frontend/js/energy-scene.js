// Simulación educativa de /soluciones. No lee ni muestra medidas reales: los niveles
// son marcas cualitativas (ninguna, poca, media, mucha), nunca cifras de una casa.
(() => {
  'use strict';
  const root = document.querySelector('[data-energy-scene]');
  if (!root) return;

  // Each flow: off, on, in (towards the far end of its route) or out (the reverse).
  // The street connects at the house panel, so grid power never crosses the inverter.
  const SCENES = {
    'day:yes': {
      title: 'De día, con batería.',
      text: 'Las placas le dan luz a la casa, lo que sobra carga la batería y el resto puede salir a la red.',
      home: 'full', flows: { solar: 'on', home: 'on', battery: 'in', grid: 'in', link: 'on' },
      meters: { solar: ['Produciendo', 3], inverter: ['Repartiendo la energía', 3], battery: ['Cargando · entra energía', 2], home: ['Con luz', 2], grid: ['Recibe lo que sobra', 1] },
    },
    'day:no': {
      title: 'De día, sin batería.',
      text: 'Las placas le dan luz a la casa y lo que sobra sale a la red. Si no alcanza, entra la luz de la calle.',
      home: 'full', flows: { solar: 'on', home: 'on', battery: 'off', grid: 'in', link: 'on' },
      meters: { solar: ['Produciendo', 3], inverter: ['Repartiendo la energía', 3], battery: ['No tiene', 0], home: ['Con luz', 2], grid: ['Recibe lo que sobra', 2] },
    },
    'night:yes': {
      title: 'De noche, con batería.',
      text: 'Las placas descansan y la batería entrega lo que guardó de día. Si no alcanza, entra la luz de la calle.',
      home: 'full', flows: { solar: 'off', home: 'on', battery: 'out', grid: 'off', link: 'on' },
      meters: { solar: ['Descansando', 0], inverter: ['Repartiendo la energía', 2], battery: ['Entregando · sale energía', 2], home: ['Con luz', 2], grid: ['Disponible', 1] },
    },
    'night:no': {
      title: 'De noche, sin batería.',
      text: 'Las placas no producen sin sol y el inversor descansa. La luz de la calle entra directo por el panel eléctrico de la casa.',
      home: 'full', flows: { solar: 'off', home: 'on', battery: 'off', grid: 'out', link: 'off' },
      meters: { solar: ['Descansando', 0], inverter: ['En reposo', 0], battery: ['No tiene', 0], home: ['Con luz', 2], grid: ['Entregando', 3] },
    },
    'outage:yes': {
      title: 'Apagón de día, con batería y respaldo.',
      text: 'El sistema se separa de la red. Con sol, las placas y la batería mantienen solo los equipos conectados al respaldo, según su tamaño y diseño. De noche queda solo la batería, y el respaldo dura mientras tenga carga.',
      home: 'partial', flows: { solar: 'on', home: 'on', battery: 'out', grid: 'off', link: 'on' },
      meters: { solar: ['Produciendo', 2], inverter: ['Separado de la red', 2], battery: ['Respaldando · sale energía', 2], home: ['Equipos de respaldo', 1], grid: ['Sin servicio', 0] },
    },
    'outage:no': {
      title: 'Apagón de día, sin batería.',
      text: 'Aunque haya sol, las placas se apagan por seguridad para no mandar electricidad a la calle mientras la reparan. La casa se queda sin luz.',
      home: 'off', flows: { solar: 'off', home: 'off', battery: 'off', grid: 'off', link: 'off' },
      meters: { solar: ['Apagadas por seguridad', 0], inverter: ['Apagado por seguridad', 0], battery: ['No tiene', 0], home: ['Sin luz', 0], grid: ['Sin servicio', 0] },
    },
  };

  const motion = window.matchMedia?.('(prefers-reduced-motion: reduce)');
  const reduced = () => Boolean(motion?.matches);
  const controls = root.querySelector('[data-energy-controls]');
  const modes = [...root.querySelectorAll('[data-energy-mode]')];
  const battery = root.querySelector('[data-energy-battery]');
  const layer = root.querySelector('[data-energy-particles]');
  const stage = root.querySelector('.es-stage');
  const sheen = root.querySelector('[data-energy-sheen]');
  const halo = root.querySelector('[data-energy-halo]');
  const level = root.querySelector('[data-energy-level]');
  const launcher = document.querySelector('.chat-launcher');
  const status = root.querySelector('.es-status');
  const titleNode = root.querySelector('[data-energy-title]');
  const textNode = root.querySelector('[data-energy-text]');
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const PER_FLOW = { solar: 3, link: 1, home: 2, battery: 3, grid: 5 };
  const SHEEN_TRAVEL = [560, 268];
  const SHEEN_PERIOD = 7;
  const HALO_PERIOD = 4.5;
  const TEXT_SWAP_MS = 200;
  const LEVEL_PERIOD = 3.2;
  const LEVEL_STEPS = 4;
  const LAUNCHER_GAP = 10;

  // Points are sampled once, so animating never forces a layout read.
  const routes = {};
  root.querySelectorAll('[data-flow]').forEach(path => {
    const length = path.getTotalLength();
    const points = [];
    for (let index = 0; index <= 48; index += 1) {
      const point = path.getPointAtLength(length * index / 48);
      points.push([point.x, point.y]);
    }
    routes[path.dataset.flow] = points;
  });

  // Halos use a prebuilt gradient: no SVG filter per particle.
  const particles = [];
  Object.entries(PER_FLOW).forEach(([flow, count]) => {
    for (let index = 0; index < count; index += 1) {
      const group = document.createElementNS(SVG_NS, 'g');
      const glow = document.createElementNS(SVG_NS, 'circle');
      const core = document.createElementNS(SVG_NS, 'circle');
      glow.setAttribute('r', flow === 'battery' ? '4.5' : '7');
      glow.setAttribute('fill', `url(#es-dot-${flow})`);
      core.setAttribute('r', flow === 'battery' ? '1.3' : '1.7');
      core.setAttribute('class', 'es-particle-core');
      group.append(glow, core);
      group.style.display = 'none';
      layer.append(group);
      particles.push({ flow, group, phase: (index + .5) / count });
    }
  });

  let mode = 'day';
  let frame = 0;
  let onScreen = false;
  let last = 0;
  let clock = 0;
  let textTimer = 0;

  const sceneKey = () => `${mode}:${battery.checked ? 'yes' : 'no'}`;
  const isIdle = () => Object.values(SCENES[sceneKey()].flows).every(state => state === 'off');

  // Charging climbs the level marks; delivering steps them down.
  function drawLevel(scene) {
    const direction = scene.flows.battery;
    let step = 0;
    if (direction === 'in') step = reduced() ? 3 : 1 + Math.floor((clock % LEVEL_PERIOD) / LEVEL_PERIOD * LEVEL_STEPS);
    if (direction === 'out') step = reduced() ? 2 : LEVEL_STEPS - Math.floor((clock % LEVEL_PERIOD) / LEVEL_PERIOD * LEVEL_STEPS);
    if (level.dataset.step !== String(step)) level.dataset.step = String(step);
  }

  function draw() {
    const scene = SCENES[sceneKey()];
    drawLevel(scene);
    particles.forEach(item => {
      const direction = scene.flows[item.flow];
      if (direction === 'off') {
        item.group.style.display = 'none';
        return;
      }
      const speed = item.flow === 'grid' ? .16 : .34;
      let progress = (item.phase + clock * speed) % 1;
      if (direction === 'out') progress = 1 - progress;
      const points = routes[item.flow];
      const exact = progress * (points.length - 1);
      const start = Math.floor(exact);
      const end = Math.min(start + 1, points.length - 1);
      const blend = exact - start;
      const x = points[start][0] + (points[end][0] - points[start][0]) * blend;
      const y = points[start][1] + (points[end][1] - points[start][1]) * blend;
      item.group.style.display = '';
      item.group.setAttribute('transform', `translate(${x.toFixed(1)} ${y.toFixed(1)})`);
      // Fades at both ends so particles do not pop in or out.
      item.group.setAttribute('opacity', Math.min(1, Math.min(progress, 1 - progress) * 9).toFixed(2));
    });
    if (reduced()) {
      sheen.setAttribute('transform', `translate(${SHEEN_TRAVEL[0] * .45} ${SHEEN_TRAVEL[1] * .45})`);
      halo.setAttribute('opacity', '1');
      return;
    }
    if (mode === 'day') {
      const sweep = (clock % SHEEN_PERIOD) / SHEEN_PERIOD;
      sheen.setAttribute('transform', `translate(${(SHEEN_TRAVEL[0] * sweep).toFixed(1)} ${(SHEEN_TRAVEL[1] * sweep).toFixed(1)})`);
    }
    if (scene.home === 'partial') {
      const breath = .82 + Math.sin(clock * Math.PI * 2 / HALO_PERIOD) * .18;
      halo.setAttribute('opacity', breath.toFixed(2));
    }
  }

  function tick(now) {
    frame = 0;
    if (!onScreen || document.hidden || reduced() || isIdle()) { last = 0; return; }
    clock += Math.min(now - (last || now), 60) / 1000;
    last = now;
    draw();
    frame = requestAnimationFrame(tick);
  }

  function syncLoop() {
    if (onScreen && !document.hidden && !reduced() && !isIdle()) {
      if (!frame) frame = requestAnimationFrame(tick);
      return;
    }
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    last = 0;
    draw();
  }

  function writeStory(scene) {
    titleNode.textContent = scene.title;
    textNode.textContent = scene.text;
  }

  // The live region changes once per selection, after the fade-out.
  function tellStory(scene, animate) {
    clearTimeout(textTimer);
    if (!animate || reduced() || document.hidden) {
      status.classList.remove('is-changing');
      writeStory(scene);
      return;
    }
    status.classList.add('is-changing');
    textTimer = setTimeout(() => {
      writeStory(SCENES[sceneKey()]);
      status.classList.remove('is-changing');
    }, TEXT_SWAP_MS);
  }

  function apply(animate = true) {
    const scene = SCENES[sceneKey()];
    root.dataset.mode = mode;
    root.dataset.battery = battery.checked ? 'yes' : 'no';
    root.dataset.home = scene.home;
    Object.entries(scene.flows).forEach(([flow, state]) => {
      root.dataset[`flow${flow[0].toUpperCase()}${flow.slice(1)}`] = state;
    });
    modes.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.energyMode === mode)));
    tellStory(scene, animate);
    Object.entries(scene.meters).forEach(([name, [label, level]]) => {
      const meter = root.querySelector(`[data-meter="${name}"]`);
      meter.querySelector('[data-meter-state]').textContent = label;
      meter.dataset.level = String(level);
    });
    syncLoop();
  }

  modes.forEach(button => button.addEventListener('click', () => {
    mode = button.dataset.energyMode;
    apply();
  }));
  battery.addEventListener('change', () => apply());
  document.addEventListener('visibilitychange', syncLoop);
  motion?.addEventListener?.('change', syncLoop);

  // The floating chat button yields only while the controls or the narration
  // actually pass under it. Geometry is read on setup and on resize, never per frame.
  let launcherWatch = null;
  let resizeFrame = 0;
  function watchLauncher() {
    launcherWatch?.disconnect();
    document.body.classList.remove('es-launcher-yield');
    if (!launcher) return;
    const box = launcher.getBoundingClientRect();
    if (!box.width) return;
    const targets = [controls, status].filter(item => {
      const rect = item.getBoundingClientRect();
      return rect.left < box.right + LAUNCHER_GAP && rect.right > box.left - LAUNCHER_GAP;
    });
    if (!targets.length) return;
    const top = Math.max(0, Math.round(box.top - LAUNCHER_GAP));
    const covered = new Set();
    launcherWatch = new IntersectionObserver(entries => {
      entries.forEach(entry => (entry.isIntersecting ? covered.add(entry.target) : covered.delete(entry.target)));
      document.body.classList.toggle('es-launcher-yield', covered.size > 0);
    }, { rootMargin: `-${top}px 0px 0px 0px` });
    targets.forEach(item => launcherWatch.observe(item));
  }
  // Reserves the height of the longest story, so changing scene never shifts the page.
  // Measures an off-screen copy: the live region itself is not rewritten.
  function reserveStoryHeight() {
    status.style.minHeight = '';
    const probe = status.cloneNode(true);
    probe.removeAttribute('id');
    probe.removeAttribute('role');
    probe.setAttribute('aria-hidden', 'true');
    probe.style.cssText = `position:absolute;visibility:hidden;min-height:0;width:${status.offsetWidth}px`;
    status.after(probe);
    const tallest = Math.max(...Object.values(SCENES).map(scene => {
      probe.querySelector('[data-energy-title]').textContent = scene.title;
      probe.querySelector('[data-energy-text]').textContent = scene.text;
      return probe.offsetHeight;
    }));
    probe.remove();
    status.style.minHeight = `${tallest}px`;
  }
  window.addEventListener('resize', () => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      reserveStoryHeight();
      watchLauncher();
    });
  }, { passive: true });

  controls.hidden = false;
  root.classList.add('is-ready');
  apply(false);
  reserveStoryHeight();
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(entries => {
      onScreen = entries.some(entry => entry.isIntersecting);
      if (onScreen) root.classList.add('is-in');
      syncLoop();
    }, { threshold: .18 }).observe(stage);
    watchLauncher();
  } else {
    onScreen = true;
    root.classList.add('is-in');
    syncLoop();
  }
})();
