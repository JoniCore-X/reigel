"""Motor comercial autónomo de R.E.I.G.E.L.

El motor decide por su cuenta qué hacer con cada registro y lo ejecuta sin que
nadie lo empuje. En esta fase los efectos son internos: crea tareas para el
asesor asignado y avisos para administración. No envía mensajes a nadie, no
marca llamadas y no cambia la etapa de un registro: esas acciones salen hacia
fuera y requieren consentimiento documentado y autorización expresa.

La frontera está en `policy.ACTIONS`: cada acción declara si es interna o
saliente, y `runtime.tick` se niega a ejecutar una acción saliente.

La memoria del agente (`memory.py`) sigue el mismo criterio: registra lo que observa
sin pedir permiso, pero solo una creencia con procedencia válida y vigente llega a un
texto dirigido a un cliente, y eso pasa por una única puerta, `speaking_context`.
"""
from .policy import ACTIONS, MODES
from .planner import evaluate
from .memory import SOURCES, SUBJECTS, speaking_context
from .runtime import tick
from .schema import migrate_agent

__all__ = ["ACTIONS", "MODES", "SOURCES", "SUBJECTS", "evaluate", "speaking_context", "tick", "migrate_agent"]
