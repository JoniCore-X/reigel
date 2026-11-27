# DESIGN.md — Dirección visual de R.E.I.G.E.L. (Team Caguas · Power Solar)

Lee este archivo completo antes de tocar cualquier cosa en `frontend/`.
Manda sobre cualquier costumbre de diseño por defecto. Si algo de aquí choca con
`AGENTS.md`, gana `AGENTS.md` en seguridad, privacidad y promesas comerciales;
este archivo gana en lo visual.

## 1. El problema que estamos resolviendo

El sitio actual está bien construido pero se ve **genérico**: sidebar azul,
tarjetas blancas con borde fino, botones naranjas, KPIs en cajitas, foto de
stock en el banner. Es el look de cualquier SaaS.

La referencia es este reel: <https://www.instagram.com/p/DgFV7Sox5K3/>
(sitio "CRYO ENERGY"): fondo oscuro, **un solo objeto 3D real** al centro que
rota y reacciona al scroll, brillo neón, transiciones suaves, casi sin texto.
Eso es lo que queremos lograr, con la identidad de Power Solar.

## 2. Dónde va el "wow" y dónde NO

| Zona | Dirección |
|---|---|
| Hero del sitio público (`/captacion`, `landing.html`) | **Inmersivo**: oscuro, escena 3D real, scroll cinemático |
| Banner superior del dashboard `/app` (Operaciones) | **Inmersivo, pequeño**: escena 3D en vez de la foto |
| Resto del CRM (Prospectos, Tareas, Agenda, Conversaciones) | **Funcional**: claro, rápido, legible. Solo pulir. No meter 3D aquí. |

El CRM es para vender rápido. El wow es para el cliente y para grabar el reel.

## 3. Por qué hasta ahora no ha salido 3D de verdad (léelo)

La CSP es `script-src 'self'`. Eso **bloquea un CDN**, pero **no bloquea una
librería guardada dentro del proyecto**. La solución no es CSS falso
(`depth-3d.js` solo simula profundidad); es **vendorizar Three.js**:

1. `npm i three` en una carpeta temporal (o `npm pack three`).
2. Copiar `node_modules/three/build/three.module.min.js` a
   `frontend/assets/vendor/three/three.module.min.js`.
3. Copiar su `LICENSE` (MIT) a `frontend/assets/licenses/three-LICENSE.txt`.
4. Cargarlo con `<script type="module" src="/static/js/solar-hero-3d.js">` y,
   dentro, `import * as THREE from '/static/assets/vendor/three/three.module.min.js';`
5. **Nada de import maps inline ni scripts inline**: la CSP los bloquea.
6. **Nada de GLTFLoader ni modelos externos** en esta fase: la escena se
   construye con geometría de Three.js (cajas, planos, cilindros). Así no hay
   dependencias de `examples/jsm` ni archivos `.glb`.

No hace falta GSAP: el progreso del scroll se calcula en JS
(`scrollY` / altura del hero, con `requestAnimationFrame`) y mueve la escena.

## 4. La escena 3D del hero (una sola idea, un solo foco)

**"Del amanecer a la energía."**

- Centro de pantalla: un **arreglo de paneles solares** (3×4 o similar) sobre un
  techo inclinado simple, construido con geometría. Celdas oscuras con líneas
  finas de rejilla y marco de aluminio.
- Iluminación: una "luz de sol" direccional que, con el scroll, sube desde el
  horizonte y pasa de ámbar profundo a blanco cálido.
- Al avanzar el scroll, las celdas se **encienden en cadena** (emissive naranja
  → ámbar) y salen **partículas/líneas de energía** hacia abajo, como corriente.
- La cámara hace un **dolly lento** y gira unos 20°. Nada brusco.
- Bloom: si no se quiere vendorizar postprocesado todavía, simularlo con
  sprites aditivos y `MeshBasicMaterial` con `AdditiveBlending`.
- Reposo: el panel rota muy lento (±6°) siguiendo el mouse en desktop.
- Texto: **un titular y un botón**. Nada más encima de la escena.

**Prohibido en el hero:** cifras de ahorro, precios, porcentajes, "garantizado"
(ver `AGENTS.md`: no se prometen ahorros). La escena **muestra** energía; no la
cuantifica.

### Rendimiento y accesibilidad (obligatorio)
- `prefers-reduced-motion: reduce` → una imagen fija renderizada (o la escena
  en su estado final, sin animar).
- Si WebGL no existe → el hero queda con el fondo oscuro y el texto; la página
  sigue completa.
- `devicePixelRatio` limitado a 2. Pausar el render cuando el hero sale de
  pantalla (`IntersectionObserver`) o la pestaña está oculta.
- Móvil: menos celdas, sin partículas pesadas. Meta: 60 fps en desktop,
  mínimo 30 en un teléfono medio.
- El `<canvas>` lleva `aria-hidden="true"`; el titular es HTML real.

## 5. Paleta (usar estos hex, no inventar)

Fondo y profundidad (solo zonas inmersivas):
- `--night-0: #03060D` fondo base
- `--night-1: #07122A` azul noche
- `--night-2: #0B1F4D` azul Power Solar profundo

Marca:
- `--ps-blue: #1E4BA8`
- `--ps-orange: #FF7A1A` acento principal / energía
- `--ps-amber: #FFB547` sol, brillo alto
- `--ps-glow: rgba(255, 122, 26, 0.45)` halo

Texto sobre oscuro: `#F4F6FB` (principal), `#9AA6C1` (secundario).

Regla: en las zonas oscuras, **el naranja es luz**, no relleno. Botones
naranjas sí; tarjetas naranjas no.

## 6. Tipografía

- Titulares del hero: grandes de verdad (`clamp(3rem, 7vw, 6.5rem)`),
  interlineado 0.95, `letter-spacing: -0.03em`. Una sola línea o dos.
- Usar la fuente de titulares que el sitio ya tiene; si se cambia, que sea una
  display con carácter (Space Grotesk, Clash Display o similar) y **local**
  (la CSP no permite Google Fonts remoto si `font-src` es `'self'`; verificar).
- Nada de Inter/Arial/system-ui en titulares.
- Rótulos pequeños en mayúsculas con tracking amplio: ya existen, mantenerlos.

## 7. Movimiento

- Todo lo que aparece entra animado (opacidad + desplazamiento corto, 400–700 ms,
  `cubic-bezier(0.22, 1, 0.36, 1)`). Nada aparece de golpe.
- El scroll del hero es **scrub** (reversible, atado a la posición), igual que
  la filosofía de `scroll-cinema.css`.
- No apilar un segundo efecto sobre un elemento que ya anima (ver la nota de
  `AGENTS.md` sobre la cascada de animaciones).

## 8. Texto y avisos legales

Hay demasiados avisos repetidos ("no confirma cobro, firma ni venta", "no
confirma una cita", etc.). Mantener la **exactitud** que pide `AGENTS.md` pero:
- Un aviso por página, en el lugar donde aplica (junto al formulario o al
  botón que crea la acción), no en cada sección.
- Nunca un aviso encima del hero.
- No borrar los que exigen los tests; si un test exige un texto, se mueve, no
  se elimina, y se ajusta el test solo si el texto sigue presente.

## 9. Banner del dashboard `/app`

Sustituir la foto de stock por un `<canvas>` con la misma escena en versión
mínima: el arreglo de paneles de lado, brillo según **actividad del periodo**
(número de prospectos/tareas, que ya da la API; nunca dinero ni ahorro).
Altura igual a la actual. El saludo y el botón "+ Nuevo prospecto" se quedan.

## 10. Prohibido en todo el proyecto

- Gradientes morados, glassmorphism genérico, sombras gigantes difusas.
- Emojis como íconos.
- Tarjetas blancas con borde fino en las zonas inmersivas.
- Tres elementos compitiendo en el hero (texto + tarjeta + foto). Un foco.
- Librerías por CDN. Todo vendorizado dentro de `frontend/assets/vendor/`.
- Romper el funcionamiento sin JS: el sitio tiene que leerse completo sin la
  escena.

## 11. Cómo trabajar

1. Una pantalla a la vez. Primero el hero de `/captacion`. No tocar el CRM
   hasta que el hero esté aprobado.
2. Antes de terminar: tomar screenshots con Playwright a 1440 y 390 de ancho,
   guardarlos en `artifacts/team-caguas/hero-3d-*.png`, compararlos contra el
   reel de referencia y corregir lo que se vea genérico. Repetir.
3. Correr la verificación de `AGENTS.md` (pytest, `node --check`, `node --test`).
4. No hacer commit ni publicar sin que Joniel lo apruebe.
