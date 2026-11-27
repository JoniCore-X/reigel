"""La escena al scrollear: que siga siendo opcional y reversible.

`frontend/css/scroll-cinema.css` ata propiedades a la posición del scroll con
`animation-timeline`. Dos cosas no pueden romperse sin que alguien se entere:

- Que todo quede detrás de `prefers-reduced-motion: no-preference`. Quien pide menos
  movimiento no recibe ninguno, y la página se queda exactamente como estaba.
- Que el texto solo se mueva. Si una animación de las que tocan texto tuviera
  `opacity`, un fallo dejaría al visitante mirando un hueco en blanco en vez de una
  línea unos píxeles corrida.

Medido el 26 de noviembre de 2026: el sitio público ya movía casi todas sus fotos
grandes (`.sc-r`, `data-sc-scrub`, `.pm-seq-fig`, `.tx-hero-media`). Una animación con
`both` gana a una declaración normal en la cascada, así que superponer un segundo
efecto no suma: sustituye. Por eso el scrub se quedó donde no pisa nada.
"""
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
HOJA = FRONTEND / "css" / "scroll-cinema.css"


def _sin_comentarios(texto):
    return re.sub(r"/\*.*?\*/", "", texto, flags=re.S)


def test_el_shell_publico_enlaza_la_hoja():
    """Una sola plantilla sirve las seis páginas públicas, así que basta un enlace."""
    shell = (FRONTEND / "landing.html").read_text(encoding="utf-8")
    assert "css/scroll-cinema.css" in shell
    assert 'class="cine-progreso"' in shell


def test_nada_se_anima_sin_la_guarda_de_movimiento_reducido():
    guarda = "prefers-reduced-motion: no-preference"
    nivel = 0
    abiertas = []  # profundidades donde se abrió una guarda, para cerrarlas a la vez
    for linea in _sin_comentarios(HOJA.read_text(encoding="utf-8")).splitlines():
        texto = linea.strip()
        if texto.startswith("@") and guarda in texto:
            abiertas.append(nivel + 1)
        elif not texto.startswith("@"):
            # Lo que enciende la escena: atar una animación al scroll, o mostrar la
            # barra de avance. Las dos cosas tienen que quedar detrás de la guarda.
            enciende = "animation-timeline" in texto or (
                "cine-progreso" in texto and "display: block" in texto)
            assert not enciende or abiertas, f"fuera de la guarda: {texto[:70]}"
        nivel += texto.count("{") - texto.count("}")
        abiertas = [p for p in abiertas if p <= nivel]
    assert abiertas == [] and nivel == 0, "la hoja tiene llaves sin cerrar"


def test_las_animaciones_de_texto_no_tocan_la_opacidad():
    """`cine-subir` es la que mueve titulares y rótulos: solo transform."""
    cuerpo = HOJA.read_text(encoding="utf-8")
    bloque = re.search(r"@keyframes cine-subir\s*\{(.*?)\n\s*\}", cuerpo, re.S)
    assert bloque, "la animación de texto tiene que existir"
    assert "opacity" not in bloque.group(1)


def test_el_recorte_no_crea_un_contenedor_de_scroll():
    """`overflow: hidden` convierte el elemento en contenedor de scroll y `view()`
    pasa a medir contra una caja que no se mueve: la animación se congela a mitad."""
    cuerpo = _sin_comentarios(HOJA.read_text(encoding="utf-8"))
    assert "overflow: hidden" not in cuerpo
    assert "overflow: clip" in cuerpo
