# Three.js vendorizado

`three.module.min.js` — three.js **r169** (`three@0.169.0`), compilación oficial
`build/three.module.min.js` del paquete de npm. Licencia MIT, copia íntegra en
`frontend/assets/licenses/three-LICENSE.txt`.

Está dentro del proyecto y no en un CDN porque la política de contenido del sitio es
`script-src 'self'`: un script de otro origen no cargaría. Se sirve desde
`/static/assets/vendor/three/three.module.min.js` y lo importa
`frontend/js/solar-hero-3d.js` por ruta absoluta —sin import map, que sería un script
en línea y la CSP también lo bloquea—.

Pesa 687 KB sin comprimir. Por eso el módulo del hero se carga con `defer`/`type=module`
y solo construye la escena si el hero existe y hay WebGL: una página sin hero no paga
nada, y el HTML se lee completo sin este archivo.

Para actualizarlo: `npm pack three@<versión>`, extraer `package/build/three.module.min.js`
y `package/LICENSE`, y sustituir ambos. No se copian `examples/jsm` ni modelos `.glb`:
la escena se construye con geometría del propio núcleo.
