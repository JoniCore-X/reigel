# Componentes públicos de Uiverse

Integración iniciada el 8 de noviembre de 2026 y ampliada el 12 de noviembre sobre
las páginas existentes de Power Solar · Team Caguas. Las referencias se adaptan a
HTML y CSS locales, con la identidad azul marino y naranja del sitio. No se
incorpora una biblioteca JavaScript remota.

## Fuentes y adaptación

El código de referencia procede del archivo oficial
[uiverse-io/galaxy](https://github.com/uiverse-io/galaxy), fijado al commit
`adbd2adde0a299a3956ea288fb444ec01891ca41`. Las páginas de cada autor y sus avisos
MIT se comprobaron durante la preparación de la integración.

| Referencia y autor | Archivo en el commit | Adaptación en Power Solar |
| --- | --- | --- |
| [Botón con flecha · satyamchaudharydev](https://uiverse.io/satyamchaudharydev/rude-wolverine-24) | `Buttons/satyamchaudharydev_rude-wolverine-24.html` | Flecha direccional y brillo de una sola pasada en las acciones. Se conserva foco visible y se elimina la animación infinita y el escalado del original. Los destinos de navegación siguen siendo enlaces. |
| [Tarjeta con esquina · SouravBandyopadhyay](https://uiverse.io/SouravBandyopadhyay/giant-squid-24) | `Cards/SouravBandyopadhyay_giant-squid-24.html` | Esquina con flecha y superficie que responde a hover/foco en enlaces del directorio y elecciones de tema. Sin altura máxima fija ni texto oculto en dispositivos táctiles. |
| [Casilla circular · krlozCJ](https://uiverse.io/krlozCJ/dull-bobcat-80) | `Checkboxes/krlozCJ_dull-bobcat-80.html` | Tratamiento circular del consentimiento real del chat y marcadores decorativos de preparación. La casilla nativa conserva teclado, etiqueta, validación `required` y estado inicial sin marcar. No se copia el `display: none` del original. |
| [Patrón de puntos · kennyotsu](https://uiverse.io/kennyotsu/short-warthog-33) | `Patterns/kennyotsu_short-warthog-33.html` | Campo de puntos estático detrás de la sección oscura de la página de equipo. Se reduce el contraste para no competir con el texto, se elimina el fondo sólido del original y no se añade animación. |
| [Botón con borde luminoso · SelfMadeSystem](https://uiverse.io/SelfMadeSystem) | No localizado en el commit fijado; código aportado por el usuario | Acción principal de conversión en `/equipo` (hero, tarjeta de contacto y cierre). Se sustituye el `div` sin nombre accesible por `<button>`/`<a>` nativos con etiqueta visible, ancho automático y píldora de 54 px. Los degradados pasan a naranja/azul de marca y el giro solo se reproduce en hover o foco; el resto del tiempo queda atenuado. Se corrigió el keyframe inválido del original y se añadieron `prefers-reduced-motion` y `forced-colors`. El halo exterior se reconstruyó con tres radios estáticos (naranja cálido, azul frío y luz central) y una capa animada atenuada para una caída uniforme en fondos claros y oscuros. |
| [Cargador de 9 esferas · 20essentials](https://uiverse.io/20essentials) | No localizado en el commit fijado; código aportado por el usuario | Capa de entrada de página en los tres shells (`/`, páginas públicas y `/app`). Se conserva la rejilla de 9 esferas × 9 ítems y el giro 3D, y los discos translúcidos conservan su relleno original con la paleta solar (rojo profundo, naranja, ámbar, oro, amarillo y pálido). Se añaden corona cónica, rayos, polvo, destellos y núcleo, sin marca ni texto visible, con entrada escalonada y salida difuminada. El fondo del overlay es transparente con difuminación del contenido detrás (`backdrop-filter`, 13 px en escritorio y 10 px en móvil) y el sol mide como máximo 300 px. La duración mínima respeta una visita nueva (1.6 s) o recurrente (650 ms) y la salida espera la carga real de la página; si la conexión falla (sin conexión, tres recursos fallidos o más de 15 s), el loader muestra un aviso con «Reintentar» y «Continuar al sitio». Se omite por puntero o `Escape`, y por completo con movimiento reducido o colores forzados. |
| [Radio neumórfico · andrew-demchenk0](https://uiverse.io/andrew-demchenk0/spicy-fish-10) | `Radio-buttons/andrew-demchenk0_spicy-fish-10.html` | Píldoras de horario de la reserva del chat de coordinación (`/chat` y el diálogo de las páginas corporativas). La bandeja oscura del original pasa a un tono claro de marca y el estado activo conserva el intercambio de sombras interiores, pero sobre `<button aria-pressed>` (no radios), con borde naranja y marca ✓ para que la selección no dependa solo de la sombra. Contorno visible con `forced-colors`. |
| [Botón con escala · AqFox](https://uiverse.io/AqFox/tasty-robin-91) | `Buttons/AqFox_tasty-robin-91.html` | Solo el botón de enviar del compositor del chat (`#chat-send.rc-send`), nunca un selector `button` genérico. Se conserva la cápsula de 50 px y la escala en hover (1.08 en lugar de 1.1); el color activo pasa al azul de marca. Sin escala ni transición con `prefers-reduced-motion`. |

La hoja de integración de controles es `frontend/css/uiverse-components.css`,
cargada al final de los shells públicos. Su ámbito se limita a las páginas
corporativas y al chat público; el espacio privado `/app` conserva sus estilos.
El chat de coordinación tiene su propia hoja, `frontend/css/coordination-chat.css`,
cargada después de todas las demás en `frontend/chat.html` y `frontend/landing.html`;
contiene las dos últimas adaptaciones de la tabla y todo su ámbito queda bajo `.reigel-chat`.
El cargador vive en archivos propios, `frontend/css/site-loader.css` y
`frontend/js/site-loader.js`, porque sí debe cubrir los tres shells.

La composición de las páginas, el recorrido numerado de evaluación, los acordeones
nativos de preguntas y el marco del formulario son trabajo original de integración.
No se atribuyen a un componente descargado de Uiverse. Los números del recorrido
describen una secuencia informativa, no el progreso real de un cliente.

## Licencia y límites

Los avisos de los ocho creadores y el texto MIT completo del archivo oficial se
conservan en
[`frontend/assets/licenses/uiverse-components.txt`](../frontend/assets/licenses/uiverse-components.txt).
Los bloques adaptados mantienen comentarios de procedencia. Las rutas de los dos componentes del chat
de coordinación proceden del encargo de rediseño (19 de noviembre de 2026); su
página pública no se volvió a consultar durante esa implementación. El aviso local puede
servirse en `/static/assets/licenses/uiverse-components.txt`.

La adaptación añade foco visible y una alternativa con movimiento reducido. El
cargador se muestra como popover manual para quedar por encima de cualquier
`<dialog>` modal (el chat público de `/`), anuncia su estado con texto para
lectores de pantalla y no atrapa el foco. No modifica el contenido interno del
formulario de Google, sus enlaces ni su desplazamiento: ese contenido pertenece a
otro origen. Una integración de estilos no demuestra publicación, entrega de
mensajes, reservas externas ni resultados comerciales.
