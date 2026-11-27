'use strict';

/* Escena del hero de /captacion: "del amanecer a la energía".
 *
 * Un solo objeto al centro —un arreglo de paneles sobre un techo inclinado— que el
 * scroll enciende mientras el sol sube. Geometría del núcleo de Three.js: ni
 * `examples/jsm`, ni cargadores, ni modelos `.glb`. Todo lo que se ve aquí son cajas,
 * planos y líneas.
 *
 * Por qué así y no de otra forma:
 * - Three.js está vendorizado en `/static/assets/vendor/three/`. La política de
 *   contenido es `script-src 'self'`, de modo que un CDN no cargaría, y un import map
 *   tampoco: sería un script en línea. Por eso la ruta del import es absoluta.
 * - El scroll se lee a mano (`scrollY` sobre la altura del hero) en vez de con una
 *   biblioteca: es una división y evita otra dependencia.
 * - Es un scrub, no un disparador: si subes, la escena retrocede. Misma filosofía que
 *   `scroll-cinema.css`, que hace lo propio en CSS para el resto de la página.
 *
 * Nada de esto es necesario para leer la página. Si falta el archivo, si no hay WebGL
 * o si el navegador no soporta módulos, queda el fondo oscuro y el texto, que es HTML
 * real. El `<canvas>` lleva `aria-hidden` porque no comunica nada que no esté escrito.
 */

import * as THREE from '/static/assets/vendor/three/three.module.min.js';

const seccion = document.querySelector('[data-solar-hero]');
if (seccion) arranca(seccion);

function arranca(hero) {
  const lienzo = hero.querySelector('.hero3d-canvas');
  if (!lienzo) return;

  const menosMovimiento = window.matchMedia('(prefers-reduced-motion: reduce)');
  const punteroFino = window.matchMedia('(hover: hover) and (pointer: fine)');
  const angosto = window.matchMedia('(max-width: 760px)');

  let render;
  try {
    render = new THREE.WebGLRenderer({ canvas: lienzo, antialias: !angosto.matches, alpha: false, powerPreference: 'high-performance' });
  } catch (error) {
    // Sin WebGL no se avisa ni se degrada a nada: el hero ya es legible sin la escena.
    hero.dataset.solarHero = 'sin-webgl';
    return;
  }

  const COLORES = {
    noche0: 0x03060d,
    noche1: 0x07122a,
    noche2: 0x0b1f4d,
    azul: 0x1e4ba8,
    naranja: 0xff7a1a,
    ambar: 0xffb547,
  };

  const escena = new THREE.Scene();
  escena.background = new THREE.Color(COLORES.noche0);
  escena.fog = new THREE.Fog(COLORES.noche0, 9, 20);

  const camara = new THREE.PerspectiveCamera(38, 1, 0.1, 60);
  const MIRA = new THREE.Vector3(1.7, 0.2, 0);
  const AMBAR = new THREE.Color(COLORES.ambar);

  // ---- El fondo: un degradado de noche, dibujado en un lienzo 2D y usado como
  // textura. Generarlo en código evita un archivo de imagen más y permite que use
  // exactamente los hex de la paleta.
  (() => {
    const c = document.createElement('canvas');
    c.width = 2; c.height = 256;
    const g = c.getContext('2d').createLinearGradient(0, 0, 0, 256);
    g.addColorStop(0, '#03060D');
    g.addColorStop(0.58, '#07122A');
    g.addColorStop(1, '#0B1F4D');
    const ctx = c.getContext('2d');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 2, 256);
    const textura = new THREE.CanvasTexture(c);
    textura.colorSpace = THREE.SRGBColorSpace;
    const malla = new THREE.Mesh(
      new THREE.PlaneGeometry(60, 30),
      new THREE.MeshBasicMaterial({ map: textura, depthWrite: false, fog: false }),
    );
    malla.position.set(0, 2, -14);
    escena.add(malla);
  })();

  // ---- El sol: un disco emisivo con halo aditivo. El `AdditiveBlending` es el
  // sustituto honesto del bloom mientras no se vendorice el postprocesado: suma luz
  // en vez de taparla, que es lo que hace que se lea como brillo y no como mancha.
  const sol = new THREE.Group();
  sol.add(new THREE.Mesh(
    new THREE.SphereGeometry(0.42, 32, 24),
    new THREE.MeshBasicMaterial({ color: COLORES.ambar, fog: false }),
  ));
  /* El halo tiene que desvanecerse hacia fuera. Una esfera aditiva no lo hace: suma
     lo mismo en el centro que en el borde, y lo que se ve es un disco marrón con
     canto duro sobre el fondo oscuro. Un degradado radial dibujado en un lienzo y
     puesto en un `Sprite` sí cae a transparente, y además el sprite siempre mira a
     la cámara, así que no hay que orientarlo. */
  const halo = (() => {
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const ctx = c.getContext('2d');
    const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    g.addColorStop(0, 'rgba(255, 181, 71, 1)');
    g.addColorStop(0.22, 'rgba(255, 140, 40, .55)');
    g.addColorStop(0.55, 'rgba(255, 122, 26, .16)');
    g.addColorStop(1, 'rgba(255, 122, 26, 0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
    const textura = new THREE.CanvasTexture(c);
    textura.colorSpace = THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: textura, blending: THREE.AdditiveBlending, depthWrite: false,
      transparent: true, opacity: 0.85, fog: false,
    }));
    sprite.scale.setScalar(7.5);
    sol.add(sprite);
    return sprite;
  })();
  sol.position.set(2.4, -2.4, -7.5);
  escena.add(sol);

  const luzSol = new THREE.DirectionalLight(COLORES.ambar, 1.4);
  escena.add(luzSol);
  escena.add(new THREE.AmbientLight(0x2a3f6b, 2.1));
  // Relleno frío por el lado opuesto y un contraluz alto: sin ellos las celdas
  // apagadas no se distinguen del fondo y el arreglo parece una plancha negra.
  const relleno = new THREE.DirectionalLight(COLORES.azul, 1.5);
  relleno.position.set(5, 3, 5);
  escena.add(relleno);
  const contra = new THREE.DirectionalLight(0x9fc4ff, 0.8);
  contra.position.set(-3, 6, -2);
  escena.add(contra);

  // ---- El techo: un plano inclinado, sin textura. Está para dar apoyo y escala al
  // arreglo; si se nota demasiado, compite con él.
  const techo = new THREE.Mesh(
    new THREE.BoxGeometry(7.1, 0.08, 3.9),
    new THREE.MeshStandardMaterial({ color: 0x132747, roughness: 0.92, metalness: 0.08 }),
  );
  escena.add(techo);

  // ---- El arreglo de paneles.
  const COLUMNAS = angosto.matches ? 3 : 4;
  const FILAS = angosto.matches ? 2 : 3;
  const ANCHO = 1.5;
  const ALTO = 0.95;
  const HUECO = 0.07;

  const arreglo = new THREE.Group();
  const paneles = [];

  const materialMarco = new THREE.MeshStandardMaterial({ color: 0x9fb0c8, roughness: 0.35, metalness: 0.85 });
  const lineas = [];

  for (let fila = 0; fila < FILAS; fila += 1) {
    for (let columna = 0; columna < COLUMNAS; columna += 1) {
      const panel = new THREE.Group();

      const marco = new THREE.Mesh(new THREE.BoxGeometry(ANCHO, 0.05, ALTO), materialMarco);
      panel.add(marco);

      // Cada celda lleva su propio material: el encendido en cadena necesita que la
      // emisión de una sea distinta de la de su vecina.
      const vidrio = new THREE.MeshStandardMaterial({
        color: 0x0b1428, roughness: 0.26, metalness: 0.78,
        emissive: new THREE.Color(COLORES.naranja), emissiveIntensity: 0,
      });
      const cara = new THREE.Mesh(new THREE.BoxGeometry(ANCHO - 0.09, 0.04, ALTO - 0.09), vidrio);
      cara.position.y = 0.02;
      panel.add(cara);

      panel.position.set(
        (columna - (COLUMNAS - 1) / 2) * (ANCHO + HUECO),
        0,
        (fila - (FILAS - 1) / 2) * (ALTO + HUECO),
      );
      arreglo.add(panel);
      paneles.push({ grupo: panel, vidrio, columna, fila });

      // Rejilla: líneas finas sobre el vidrio. `LineSegments` en una sola malla por
      // panel es más barato que una caja por línea.
      const puntos = [];
      const mx = (ANCHO - 0.09) / 2;
      const mz = (ALTO - 0.09) / 2;
      for (let i = 1; i < 6; i += 1) {
        const x = -mx + (2 * mx * i) / 6;
        puntos.push(x, 0.045, -mz, x, 0.045, mz);
      }
      for (let i = 1; i < 3; i += 1) {
        const z = -mz + (2 * mz * i) / 3;
        puntos.push(-mx, 0.045, z, mx, 0.045, z);
      }
      const geoLinea = new THREE.BufferGeometry();
      geoLinea.setAttribute('position', new THREE.Float32BufferAttribute(puntos, 3));
      const matLinea = new THREE.LineBasicMaterial({ color: 0x2b4d86, transparent: true, opacity: 0.55 });
      const rejilla = new THREE.LineSegments(geoLinea, matLinea);
      panel.add(rejilla);
      lineas.push(matLinea);
    }
  }

  /* Signo positivo: inclina la cara del panel HACIA la cámara. Con -0.58 la normal
     apuntaba al lado contrario y, con la cámara solo 14° por encima, el arreglo se
     veía de canto: un paralelogramo negro sin rejilla ni marco. Un panel real se
     inclina hacia el sol, que aquí está detrás, pero lo que tiene que leerse en un
     hero es la cara. */
  const INCLINACION = 0.3;
  arreglo.rotation.x = INCLINACION;
  arreglo.position.y = 0.3;
  techo.rotation.x = INCLINACION;
  techo.position.y = 0.16;

  // El conjunto, a escala y a la derecha: la mitad izquierda del encuadre es del
  // titular. A tamaño natural el techo ocupaba el 76 % del ancho visible y se leía
  // como una plancha negra en vez de como un tejado con paneles.
  const conjunto = new THREE.Group();
  conjunto.add(techo, arreglo);
  conjunto.scale.setScalar(0.62);
  conjunto.position.set(2.35, 0.1, 0);
  escena.add(conjunto);

  // ---- La corriente: líneas de energía que bajan desde el arreglo. En móvil no se
  // crean; es el gasto más fácil de recortar y el que menos se echa en falta.
  const corriente = angosto.matches ? null : (() => {
    const CUANTAS = 90;
    const posiciones = new Float32Array(CUANTAS * 3);
    const caidas = new Float32Array(CUANTAS);
    for (let i = 0; i < CUANTAS; i += 1) {
      posiciones[i * 3] = 1.9 + (Math.random() - 0.5) * 4.2;
      posiciones[i * 3 + 1] = Math.random() * -2.6;
      posiciones[i * 3 + 2] = (Math.random() - 0.5) * 3.4;
      caidas[i] = 0.4 + Math.random() * 0.9;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(posiciones, 3));
    const mat = new THREE.PointsMaterial({
      color: COLORES.ambar, size: 0.055, transparent: true, opacity: 0,
      blending: THREE.AdditiveBlending, depthWrite: false, fog: false,
    });
    const puntos = new THREE.Points(geo, mat);
    escena.add(puntos);
    return { puntos, mat, geo, caidas, CUANTAS };
  })();

  // ---- Estado del scroll y del puntero.
  let avance = 0;          // 0 a 1 según el hero cruza la pantalla
  let ratonX = 0, ratonY = 0;
  let objetivoX = 0, objetivoY = 0;
  let visible = true;
  let pedido = 0;
  let ultimo = 0;

  function mideAvance() {
    const caja = hero.getBoundingClientRect();
    const recorrido = Math.max(1, caja.height);
    return Math.min(1, Math.max(0, -caja.top / recorrido));
  }

  function redimensiona() {
    const ancho = hero.clientWidth;
    const alto = hero.clientHeight;
    if (!ancho || !alto) return;
    render.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    render.setSize(ancho, alto, false);
    camara.aspect = ancho / alto;
    camara.updateProjectionMatrix();
  }

  /* El encendido en cadena.
   *
   * Un frente de luz recorre el arreglo en diagonal: las celdas de arriba a la
   * izquierda se encienden primero y las de abajo a la derecha al final. `frente` es
   * dónde está ese borde, y `0.45` lo ancho que es —cuanto más estrecho, más se nota
   * la cadena; cuanto más ancho, más parece que todo sube a la vez—. El 1.35 deja que
   * el frente salga del arreglo antes de terminar, para que las últimas celdas lleguen
   * a encenderse del todo. */
  function brilloDeCelda(panel, progreso) {
    const diagonal = (panel.columna / Math.max(1, COLUMNAS - 1) + panel.fila / Math.max(1, FILAS - 1)) / 2;
    const frente = progreso * 1.35 - 0.1;
    return Math.min(1, Math.max(0, (frente - diagonal) / 0.45));
  }

  function dibuja(ahora) {
    pedido = 0;
    const delta = Math.min(0.05, (ahora - ultimo) / 1000 || 0.016);
    ultimo = ahora;

    /* `avance` llega a 1 cuando el hero ha salido del todo por arriba, y para
       entonces ya no lo ve nadie: medido el 26 nov 2026, a mitad de recorrido solo
       había una celda encendida y la cadena se completaba fuera de pantalla. El
       0.55 mete toda la escena en el tramo en el que el hero aún se ve.

       Con movimiento reducido no hay recorrido: se dibuja el estado final una vez,
       que es la escena encendida y quieta. */
    const p = menosMovimiento.matches ? 1 : Math.min(1, avance / 0.55);

    // El sol sube desde el horizonte y se vuelve blanco cálido.
    sol.position.y = -2.4 + p * 4.0;
    const tono = new THREE.Color(COLORES.naranja).lerp(new THREE.Color(0xfff2d6), p);
    luzSol.color.copy(tono);
    luzSol.intensity = 1.1 + p * 1.5;
    luzSol.position.copy(sol.position).multiplyScalar(1.1);
    halo.material.opacity = 0.55 + p * 0.4;
    halo.scale.setScalar(7.5 + p * 2.6);

    // Las celdas se encienden en cadena.
    paneles.forEach(panel => {
      const brillo = brilloDeCelda(panel, p);
      // Tope en 0.9 y no en 1.25: a plena emisión la celda se vuelve un rectángulo
      // naranja liso y se pierde la rejilla, que es lo que la hace parecer un panel.
      panel.vidrio.emissiveIntensity = brillo * 0.9;
      panel.vidrio.emissive.setHex(COLORES.naranja).lerp(AMBAR, brillo);
    });
    lineas.forEach(linea => { linea.opacity = 0.4 + p * 0.5; });

    // La corriente baja; aparece solo cuando ya hay algo encendido.
    if (corriente) {
      const pos = corriente.geo.attributes.position;
      for (let i = 0; i < corriente.CUANTAS; i += 1) {
        let y = pos.getY(i) - corriente.caidas[i] * delta * (0.6 + p * 1.8);
        if (y < -3.2) y = 0.6;
        pos.setY(i, y);
      }
      pos.needsUpdate = true;
      corriente.mat.opacity = Math.max(0, p - 0.22) * 0.9;
    }

    // Reposo: el arreglo sigue al ratón ±6°, y el scroll hace el dolly y el giro.
    if (!menosMovimiento.matches && punteroFino.matches) {
      ratonX += (objetivoX - ratonX) * Math.min(1, delta * 4);
      ratonY += (objetivoY - ratonY) * Math.min(1, delta * 4);
    }
    const SEIS_GRADOS = 0.1047;
    conjunto.rotation.y = ratonX * SEIS_GRADOS + p * 0.35;
    arreglo.rotation.x = INCLINACION + ratonY * SEIS_GRADOS * 0.5;
    techo.rotation.x = arreglo.rotation.x;

    // 37° de picado: suficiente para ver las celdas, no tanto como para que el
    // arreglo se aplane en un rectángulo.
    camara.position.set(
      -0.4 + Math.sin(p * 0.35) * 1.8,
      5.0 - p * 1.1,
      6.4 - p * 1.1,
    );
    camara.lookAt(MIRA);

    render.render(escena, camara);
    if (visible && !menosMovimiento.matches) pide();
  }

  function pide() {
    if (!pedido) pedido = window.requestAnimationFrame(dibuja);
  }

  function alScrollear() {
    avance = mideAvance();
    if (visible) pide();
  }

  // Fuera de pantalla no se dibuja: es el hero, así que en cuanto el visitante baja
  // un poco el bucle para solo.
  const mirilla = new IntersectionObserver(entradas => {
    visible = entradas[0].isIntersecting;
    if (visible) { alScrollear(); }
    else if (pedido) { window.cancelAnimationFrame(pedido); pedido = 0; }
  }, { threshold: 0 });
  mirilla.observe(hero);

  window.addEventListener('scroll', alScrollear, { passive: true });
  window.addEventListener('resize', () => { redimensiona(); pide(); }, { passive: true });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') { if (visible) pide(); }
    else if (pedido) { window.cancelAnimationFrame(pedido); pedido = 0; }
  });

  if (punteroFino.matches) {
    hero.addEventListener('pointermove', evento => {
      const caja = hero.getBoundingClientRect();
      objetivoX = ((evento.clientX - caja.left) / caja.width - 0.5) * 2;
      objetivoY = ((evento.clientY - caja.top) / caja.height - 0.5) * 2;
      pide();
    }, { passive: true });
  }

  menosMovimiento.addEventListener?.('change', () => { avance = mideAvance(); pide(); });

  redimensiona();
  avance = mideAvance();
  hero.dataset.solarHero = 'activo';
  pide();
}
