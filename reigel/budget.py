"""Presupuesto de tokens: qué entra en el prompt y qué se queda fuera.

Ollama recorta sin avisar cuando el prompt no cabe en `num_ctx`, y recorta por donde
le toca, no por donde conviene. El 26 de noviembre de 2026 eso dejaba a los borradores
leyendo 1026 tokens de los 2179 que tenía su mensaje de sistema: redactaban sin la
mayoría de sus reglas y ninguna respuesta pasaba los validadores.

Aquí la decisión se toma antes de enviar, y con un orden explícito:

1. **Lo crítico no se toca.** El mensaje de sistema —que lleva las reglas, la voz y lo
   que nunca se dice— y el mensaje de la persona entran siempre enteros.
2. **Lo secundario se recorta por el principio.** El historial se va soltando desde el
   turno más viejo, que es el que menos aporta a la respuesta de ahora.
3. **Si ni así cabe, no se envía.** Un prompt sin sus reglas no es una versión peor de
   la respuesta: es otra cosa. Quien llama se queda sin respuesta del modelo y usa su
   camino de respaldo, que es el comportamiento que ya tenía el sistema al fallar.

La cuenta es por caracteres, no por el tokenizador del modelo: así no hay que cargarlo
para decidir, y la relación se midió sobre estos mismos prompts. `CHARS_PER_TOKEN` es
pesimista a propósito, porque equivocarse por abajo se paga con instrucciones perdidas.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

# 7788 caracteres fueron 2179 tokens con qwen2.5:3b: 3.57 por token. Se usa 3.3.
CHARS_PER_TOKEN = 3.3
# Lo que el formato de chat añade por mensaje (marcas de turno y de rol).
TOKENS_PER_MESSAGE = 4


def estimate(text) -> int:
    """Tokens que ocupará un texto, redondeando hacia arriba."""
    return math.ceil(len(str(text or "")) / CHARS_PER_TOKEN)


@dataclass
class Plan:
    """Qué cabe y qué no, decidido antes de enviar."""

    num_ctx: int
    reply: int
    critical: int                       # sistema + mensaje de la persona
    kept: list = field(default_factory=list)   # historial que sí entra, en orden
    dropped: int = 0                    # turnos de historial que se quedaron fuera
    overflow: bool = False              # ni sin historial cabe lo crítico

    @property
    def total(self) -> int:
        return self.critical + sum(estimate(item) + TOKENS_PER_MESSAGE for item in self.kept)

    @property
    def trimmed(self) -> bool:
        return self.dropped > 0

    def describe(self) -> str:
        return (f"{self.total} de {self.num_ctx} tokens, {self.reply} reservados para responder"
                f", {self.dropped} turnos fuera")


def fit(system: str, turns, tail: str, *, num_ctx: int, reply: int, logger_name: str = __name__) -> Plan:
    """Decide qué historial entra. `turns` es una lista de textos ya formados.

    Devuelve siempre un plan: con `overflow` en verdadero cuando lo crítico no cabe,
    para que quien llama se niegue en lugar de enviar un prompt mutilado.
    """
    critical = (estimate(system) + TOKENS_PER_MESSAGE
                + estimate(tail) + TOKENS_PER_MESSAGE)
    plan = Plan(num_ctx=num_ctx, reply=reply, critical=critical)
    available = num_ctx - reply - critical
    if available < 0:
        plan.overflow = True
        plan.dropped = len(list(turns))
        logging.getLogger(logger_name).error(
            "El prompt no cabe ni sin historial: %d tokens de instrucciones y mensaje,"
            " %d de ventana y %d reservados para responder. No se envía.",
            critical, num_ctx, reply)
        return plan
    # Del turno más reciente hacia atrás: lo último dicho es lo que más pesa.
    kept = []
    for item in reversed(list(turns)):
        cost = estimate(item) + TOKENS_PER_MESSAGE
        if cost > available:
            break
        available -= cost
        kept.append(item)
    plan.kept = list(reversed(kept))
    plan.dropped = len(list(turns)) - len(plan.kept)
    if plan.trimmed:
        logging.getLogger(logger_name).warning(
            "Historial recortado para que el prompt quepa: %d turnos fuera (%s).",
            plan.dropped, plan.describe())
    return plan
