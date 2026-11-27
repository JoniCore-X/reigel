'use strict';

/* Banner de Operaciones: el arreglo de paneles, de lado y en pequeño.
 *
 * Es la misma gramática que el hero de /captacion, en versión mínima: una fila de
 * paneles vista desde un lado, quieta, con un brillo que responde a la actividad del
 * periodo. Aquí no hay scroll que seguir —el banner vive arriba del panel— así que la
 * escena no se anima sola: se dibuja cuando cambia algo y se detiene.
 *
 * El brillo sale del **número de registros del periodo**, nunca de dinero. Un panel
 * que brillara con los importes convertiría una cifra declarada por el equipo en una
 * señal de éxito, y esos importes no demuestran facturación ni cobro.
 *
 * Montaje y desmontaje: `operations.js` reescribe el contenido en cada navegación, de
 * modo que el elemento aparece y desaparece. Un observador lo vigila y, cuando se va,
 * libera el contexto WebGL. Sin eso, nueve o diez vueltas al panel agotan los
 * contextos que el navegador concede por página y el banner deja de dibujarse.
 *
 * Si no hay WebGL o falla la carga, queda el fondo oscuro del CSS con su texto. El
 * `<canvas>` lleva `aria-hidden`: no dice nada que no esté escrito al lado.
 */

import * as THREE from '/static/assets/vendor/three/three.module.min.js';

const COLORES = { noche0: 0x03060d, noche2: 0x0b1f4d, azul: 0x1e4ba8, naranja: 0xff7a1a, ambar: 0xffb547 };
const menosMovimiento = window.matchMedia('(prefers-reduced-motion: reduce)');

let vivo = null;

function monta(banner) {
  const lienzo = banner.querySelector('.ops-banner-canvas');
  if (!lienzo) return null;

  let render;
  try {
    render = new THREE.WebGLRenderer({ canvas: lienzo, antialias: true, alpha: true });
  } catch (error) {
    banner.dataset.opsBanner = 'sin-webgl';
    return null;
  }
  render.setClearAlpha(0);

  const escena = new THREE.Scene();
  const camara = new THREE.PerspectiveCamera(32, 3, 0.1, 40);

  escena.add(new THREE.AmbientLight(0x2a3f6b, 2.4));
  const relleno = new THREE.DirectionalLight(COLORES.azul, 1.3);
  relleno.position.set(4, 3, 5);
  escena.add(relleno);
  const luz = new THREE.DirectionalLight(COLORES.ambar, 1.2);
  luz.position.set(-3, 4, 2);
  escena.add(luz);

  // Una sola fila de cinco paneles, de lado. Menos piezas que en el hero: este
  // banner mide poco más de cien píxeles de alto y el detalle no se vería.
  const fila = new THREE.Group();
  const vidrios = [];
  const marco = new THREE.MeshStandardMaterial({ color: 0x9fb0c8, roughness: 0.35, metalness: 0.85 });
  for (let i = 0; i < 5; i += 1) {
    const panel = new THREE.Group();
    panel.add(new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.05, 0.92), marco));
    const vidrio = new THREE.MeshStandardMaterial({
      color: 0x0b1428, roughness: 0.26, metalness: 0.78,
      emissive: new THREE.Color(COLORES.naranja), emissiveIntensity: 0,
    });
    const cara = new THREE.Mesh(new THREE.BoxGeometry(1.31, 0.04, 0.83), vidrio);
    cara.position.y = 0.02;
    panel.add(cara);

    const puntos = [];
    for (let j = 1; j < 5; j += 1) {
      const x = -0.655 + (1.31 * j) / 5;
      puntos.push(x, 0.045, -0.415, x, 0.045, 0.415);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(puntos, 3));
    panel.add(new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: 0x2b4d86, transparent: true, opacity: 0.6 })));

    panel.position.x = (i - 2) * 1.5;
    fila.add(panel);
    vidrios.push(vidrio);
  }
  // Menos giro lateral del que parecía razonable: con -0.42 la fila se veía casi de
  // canto y quedaba en una astilla diagonal. El mismo error que en el hero.
  fila.rotation.set(0.42, -0.2, 0);
  escena.add(fila);

  camara.position.set(0.5, 3.1, 4.9);
  camara.lookAt(0, 0, 0);

  /* De cuántos registros a cuánta luz.
   *
   * `1 - e^(-n/k)` sube rápido en los primeros registros y se va aplanando: la
   * diferencia entre cero y cinco se nota mucho, y entre cuarenta y cincuenta casi
   * nada, que es como se siente de verdad un periodo de trabajo. Nunca llega a cero
   * —el suelo de 0.1 deja los paneles presentes en un periodo vacío, no apagados— ni
   * satura. Con k = 14, unos catorce registros dan dos tercios del brillo.
   *
   * `k` y el suelo son los dos números que conviene ajustar cuando se vea con datos
   * reales del equipo. */
  function luzDeActividad(registros) {
    return 0.1 + 0.9 * (1 - Math.exp(-Math.max(0, registros) / 14));
  }

  let pedido = 0;
  function dibuja() {
    pedido = 0;
    const registros = Number(banner.dataset.actividad || 0);
    const brillo = luzDeActividad(registros);
    vidrios.forEach((vidrio, i) => {
      // Los de la izquierda se encienden antes: la fila se lee de principio a fin.
      const suyo = Math.min(1, Math.max(0, brillo * 5 - i * 0.6));
      vidrio.emissiveIntensity = suyo * 0.85;
      vidrio.emissive.setHex(COLORES.naranja).lerp(new THREE.Color(COLORES.ambar), suyo);
    });
    render.render(escena, camara);
  }

  function pide() { if (!pedido) pedido = window.requestAnimationFrame(dibuja); }

  function redimensiona() {
    const ancho = banner.clientWidth;
    const alto = banner.clientHeight;
    if (!ancho || !alto) return;
    render.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    render.setSize(ancho, alto, false);
    camara.aspect = ancho / alto;
    camara.updateProjectionMatrix();
    pide();
  }

  const medidor = new ResizeObserver(redimensiona);
  medidor.observe(banner);
  redimensiona();
  banner.dataset.opsBanner = menosMovimiento.matches ? 'quieto' : 'activo';

  return {
    banner,
    suelta() {
      medidor.disconnect();
      if (pedido) window.cancelAnimationFrame(pedido);
      escena.traverse(nodo => {
        nodo.geometry?.dispose();
        if (Array.isArray(nodo.material)) nodo.material.forEach(m => m.dispose());
        else nodo.material?.dispose();
      });
      render.dispose();
    },
  };
}

function revisa() {
  const banner = document.querySelector('[data-ops-banner]');
  if (vivo && vivo.banner !== banner) { vivo.suelta(); vivo = null; }
  if (banner && !vivo) vivo = monta(banner);
}

const destino = document.querySelector("#view-content") || document.body;
new MutationObserver(revisa).observe(destino, { childList: true, subtree: true });
revisa();
