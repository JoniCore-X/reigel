"""Respuestas fijas para mantenimiento, limpieza, daños y emergencias.

Estas preguntas no llegan al modelo: con llama3.2:3b produjeron consejos como
limpiar placas con un paño o agua, y un filtro de palabras no puede juzgar si
una explicación es segura. El detector es determinista y conservador: distingue
una avería («el inversor se dañó») de una duda general («¿por qué el sistema no
funciona en un apagón?»).
"""
from __future__ import annotations

import re
import unicodedata

_EQUIPMENT = r"(?:placas?|paneles?|inversor(?:es)?|microinversor(?:es)?|bater[i]as?|cables?|sistema|equipos?|breakers?|contador)"

_EMERGENCY = re.compile(
    r"\bhumo\b|\bchispas?\b|\bchispea|\bfuego\b|\bincendio|\bse quema|\bse esta quemando|olor a quemado|huele a quemado|"
    r"\belectrocut|\bcorrientazo|\bdescarga electrica|\bme dio corriente|cables? (?:caido|pelado|suelto)s?"
)
_STORM = re.compile(
    r"(?:despues|luego|tras)\s+(?:de\s+)?(?:una?|la|el)?\s*(?:tormenta|huracan)\b.*"
    r"\b(?:revis|usar|prender|encender|reconect|volver|toc|mirar)|"
    r"\b(?:revis|usar|prender|encender|reconect|volver|toc|mirar)\w*\b.*(?:despues|luego|tras)\s+(?:de\s+)?(?:una?|la|el)?\s*(?:tormenta|huracan)\b"
)
_CLEANING = re.compile(
    rf"\blimpi\w*\b.*\b{_EQUIPMENT}\b|\b{_EQUIPMENT}\b.*\blimpi\w*\b|\blimpiar(?:las|los)\b|\blimpieza de\b.*\b{_EQUIPMENT}\b|"
    r"\bsubir(?:me)? al techo\b"
)
_HANDLING = re.compile(
    rf"\b(?:abr(?:ir|o)|arregl\w*|repar(?:ar|o)\w*|desarm\w*|desconect\w*|toc(?:ar|o)\w*|mover|muevo)\s+(?:\w+\s+){{0,3}}?{_EQUIPMENT}\b"
)
_DAMAGE = re.compile(
    rf"\b{_EQUIPMENT}\b[^.?!]{{0,50}}\b(?:se (?:me |nos )?dan\w*|danad\w*|rot[oa]s?|quemad\w*|averiad\w*|mojad\w*|inundad\w*|"
    r"fallando|falla|fallo|sueltas?|sueltos?)\b|"
    rf"\b(?:se (?:me |nos )?dano|se (?:me |nos )?rompio|se (?:me |nos )?averio)\b[^.?!]{{0,50}}\b{_EQUIPMENT}\b|"
    r"\bsi se (?:me |nos )?(?:dana|danan|rompe|rompen)\b"
)
_NOT_WORKING = re.compile(rf"\b{_EQUIPMENT}\b[^.?!]{{0,40}}\bno (?:funciona|funcionan|prende|prenden|enciende|encienden)\b")
_OUTAGE = re.compile(r"apagon|se (?:me |nos |te |le )?va la luz|se (?:me |nos |te |le )?fue la luz|sin luz|de noche")
_MAINTENANCE = re.compile(r"\bmantenimiento\b")

_REPLIES = {
    "emergency": (
        "Si hay humo, chispas, fuego, olor a quemado o un cable caído, aléjate y saca a todos de la casa. "
        "Llama al 911. No toques los equipos ni trates de apagarlos tú."
    ),
    "storm": (
        "Después de una tormenta, no subas al techo ni toques los equipos, aunque todo parezca apagado. "
        "Mira solo desde lejos. Si ves placas sueltas, cables caídos o agua cerca de los equipos, aléjate y "
        "llama a un técnico cualificado antes de volver a usar el sistema. {handoff}"
    ),
    "cleaning": (
        "No subas al techo ni limpies las placas tú: te puedes caer y pueden tener electricidad, aunque "
        "parezcan apagadas. Si las ves muy sucias, llama a un técnico cualificado. {handoff}"
    ),
    "damage": (
        "No toques ese equipo, no lo abras y no trates de arreglarlo, aunque parezca algo pequeño. "
        "Mantén a todos lejos y llama a un técnico cualificado. {handoff}"
    ),
    "maintenance": (
        "Lo seguro es que un técnico cualificado revise el sistema. Tú no tienes que subir al techo ni tocar "
        "los equipos: mira desde el suelo y, si notas algo raro, llámalo. {handoff}"
    ),
}

HANDOFF_IA = "Si quieres hablar con alguien del equipo, usa «Citas y equipo» en esta pantalla."
HANDOFF_CHAT = "Si quieres hablar con alguien del equipo, pide atención humana aquí mismo."


def _plain(value):
    decomposed = unicodedata.normalize("NFKD", str(value or "").replace("ñ", "n").replace("Ñ", "n"))
    return " ".join("".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold().split())


def classify(text):
    """Returns the safety topic of a message, most urgent first, or None."""
    value = _plain(text)
    if not value:
        return None
    if _EMERGENCY.search(value):
        return "emergency"
    if _STORM.search(value):
        return "storm"
    if _CLEANING.search(value):
        return "cleaning"
    if _DAMAGE.search(value) or _HANDLING.search(value):
        return "damage"
    if _NOT_WORKING.search(value) and not _OUTAGE.search(value):
        return "damage"
    if _MAINTENANCE.search(value):
        return "maintenance"
    return None


def reply_for(text, handoff=HANDOFF_IA):
    topic = classify(text)
    return _REPLIES[topic].format(handoff=handoff).strip() if topic else None
