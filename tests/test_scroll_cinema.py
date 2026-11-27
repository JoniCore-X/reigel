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
    """Lo que explica por qué se quitó algo nombra lo que se quitó: si el comentario
    contara como código, estas comprobaciones fallarían por decir la verdad."""
    sin_bloque = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    return "\n".join(l for l in sin_bloque.splitlines() if not l.lstrip().startswith("//"))


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


# --- La aparición, convertida de disparador a scrub el 26 de noviembre de 2026 ---

MOSTRADOR = FRONTEND / "css" / "system-showcase.css"
GUION = FRONTEND / "js" / "system-showcase.js"


def test_el_disparador_viejo_no_queda_a_medias():
    """`.sc-armed` lo ponía un IntersectionObserver que ya no existe. Media conversión
    —el JavaScript fuera y las reglas dentro, o al revés— deja bloques invisibles."""
    for archivo in (MOSTRADOR, GUION):
        cuerpo = _sin_comentarios(archivo.read_text(encoding="utf-8"))
        assert "sc-armed" not in cuerpo, archivo.name
    assert "IntersectionObserver" not in _sin_comentarios(GUION.read_text(encoding="utf-8"))


def test_la_aparicion_esta_atada_al_scroll_y_conserva_su_escalonado():
    cuerpo = _sin_comentarios(HOJA.read_text(encoding="utf-8"))
    regla = re.search(r"\[data-sc-reveal\] \.sc-r \{(.*?)\}", cuerpo, re.S)
    assert regla, "la aparición tiene que seguir existiendo"
    assert "animation-timeline: view()" in regla.group(1)
    # `--i` ya venía en el marcado: el escalonado se mide en scroll, no en tiempo.
    assert "var(--i" in regla.group(1)


def test_los_marcos_que_anima_el_scroll_recortan_con_clip():
    """Un ancestro con `overflow: hidden` congela `view()` aunque la regla esté bien.
    Pasó con `.sc-stage`: el punto se quedaba a opacidad 0,38 dentro de la pantalla."""
    cuerpo = _sin_comentarios(MOSTRADOR.read_text(encoding="utf-8"))
    for clase in ("sc-storm-media", "sc-edge-frame", "sc-stage"):
        bloque = re.search(r"\.corporate-body \." + clase + r" \{([^}]*)\}", cuerpo)
        assert bloque, clase
        assert "overflow: hidden" not in bloque.group(1), clase


def test_en_papel_no_se_imprimen_bloques_invisibles():
    """Sin scroll que seguir, cada animación se quedaría en su primer fotograma."""
    cuerpo = HOJA.read_text(encoding="utf-8")
    impresion = cuerpo[cuerpo.index("@media print"):]
    assert "opacity: 1 !important" in impresion
    assert "transform: none !important" in impresion
