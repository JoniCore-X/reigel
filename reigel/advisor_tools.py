"""Purpose-limited staff preparation and explicitly simulated sales practice.

These tools never generate commercial actions, messages or technical certifications.
The rubric is intentionally transparent: its scores measure text signals only.
"""
from __future__ import annotations

import re
import unicodedata

from fastapi import Depends, Request

from .core import DomainError, text


SCENARIOS = (
    {"id": "cost", "title": "Le preocupa el costo", "customer_message": "Me parece caro y no sé si puedo pagarlo.",
     "focus": ["costo", "presupuesto", "comparar", "pagar"]},
    {"id": "existing", "title": "Ya tiene placas", "customer_message": "Ya tengo placas solares. ¿Para qué hablar de otro sistema?",
     "focus": ["sistema", "placas", "actual", "necesidad"]},
    {"id": "trust", "title": "Desconfía de la oferta", "customer_message": "He escuchado promesas falsas y no confío en lo que ofrecen.",
     "focus": ["confianza", "verificar", "document", "promesa", "escrito"]},
    {"id": "backup", "title": "Le interesan las baterías", "customer_message": "Quiero respaldo durante apagones. ¿La batería sostiene toda la casa?",
     "focus": ["respaldo", "cargas", "bateria", "consumo", "autonomia"]},
    {"id": "compare", "title": "Compara propuestas", "customer_message": "Tengo otra propuesta. ¿Por qué debería considerar esta?",
     "focus": ["comparar", "propuesta", "condiciones", "alcance", "document"]},
    {"id": "time", "title": "Quiere pensarlo", "customer_message": "Quiero pensarlo con calma antes de decidir.",
     "focus": ["tiempo", "calma", "pensar", "decidir", "dudas"]},
    {"id": "finance", "title": "Pregunta por financiación", "customer_message": "¿Me aprueban el financiamiento y cuánto voy a pagar?",
     "focus": ["financ", "evaluacion", "condiciones", "aproba", "pago"]},
)

RUBRIC = (
    {"id": "clarity", "label": "Claridad", "criterion": "Dos puntos: entre 40 y 600 caracteres, sin bloques de mayúsculas; uno: texto más largo o menos desarrollado."},
    {"id": "accuracy", "label": "Precisión", "criterion": "Dos puntos: reconoce condiciones o verificación y no usa promesas absolutas; uno: sin promesas detectadas, sin matiz verificable; cero: promesa detectada."},
    {"id": "listening", "label": "Escucha", "criterion": "Dos puntos: reconoce la inquietud y menciona el tema del escenario; uno: solo una de esas señales."},
    {"id": "objection", "label": "Manejo de objeción", "criterion": "Dos puntos: aborda el tema y propone aclararlo o compararlo; uno: solo aborda el tema."},
    {"id": "respect", "label": "Respeto", "criterion": "Dos puntos: ofrece elección o pide permiso, sin presión detectada; uno: sin presión detectada; cero: presión detectada."},
    {"id": "next_step", "label": "Próximo paso", "criterion": "Dos puntos: sugiere una acción y pide permiso o hace una pregunta; uno: solo una de esas señales."},
)


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def evaluate_practice(data):
    if not isinstance(data, dict) or set(data) - {"scenario_id", "response"}:
        raise DomainError("Revisa los campos de la práctica.", 422)
    scenario_id = text(data.get("scenario_id"), "escenario", required=True, limit=40)
    scenario = next((item for item in SCENARIOS if item["id"] == scenario_id), None)
    if scenario is None:
        raise DomainError("Elige un escenario disponible.", 422)
    answer = text(data.get("response"), "respuesta simulada", required=True, limit=2500)
    if len(answer) < 10:
        raise DomainError("Desarrolla una respuesta simulada de al menos diez caracteres.", 422)
    value = normalized(answer)
    topic = any(word in value for word in scenario["focus"])
    acknowledgement = bool(re.search(r"\b(entiendo|comprendo|escucho|preocupa|gracias|tiene sentido|es razonable)\b", value))
    verification = bool(re.search(r"\b(depende|evaluar|evaluacion|verificar|revisar|condiciones|estimad\w*|document\w*|no puedo prometer)\b", value))
    # Explicitly conservative signals, not a claim to understand every assertion.
    promise = bool(re.search(r"\b(garantiz\w*|aprobado|aprobamos|gratis|sin costo|te ahorras|ahorraras|cita confirmada|ya reserve)\b|100\s*%|\$\s*\d", value))
    pressure = bool(re.search(r"\b(ultima oportunidad|solo hoy|tienes que firmar|debes comprar|no seas|tonto|ignorante)\b", value))
    permission = bool(re.search(r"\b(si quieres|si deseas|si te parece|cuando prefieras|sin compromiso|te parece|podemos|te gustaria|prefieres)\b", value))
    action = bool(re.search(r"\b(revisar|comparar|coordinar|evaluar|conversar|explicar|aclarar|agendar|consultar)\b", value))
    question = "?" in answer or "¿" in answer
    scores = {
        "clarity": 2 if 40 <= len(answer) <= 600 and not re.search(r"\b[A-ZÁÉÍÓÚÑ]{6,}\b", answer) else 1,
        "accuracy": 0 if promise else 2 if verification else 1,
        "listening": int(topic) + int(acknowledgement),
        "objection": int(topic) + int(topic and action),
        "respect": 0 if pressure else 2 if permission else 1,
        "next_step": int(action) + int(action and (permission or question)),
    }
    evidence = {
        "clarity": f"Extensión observada: {len(answer)} caracteres; se comprueba también el uso de mayúsculas.",
        "accuracy": "Se detectó una expresión de promesa o importe sin verificar." if promise else "Se detectó lenguaje de condiciones o revisión." if verification else "No se detectaron condiciones o verificación explícitas.",
        "listening": f"Tema del escenario: {'detectado' if topic else 'no detectado'}; reconocimiento de la inquietud: {'detectado' if acknowledgement else 'no detectado'}.",
        "objection": f"Tema: {'detectado' if topic else 'no detectado'}; acción para aclararlo: {'detectada' if action else 'no detectada'}.",
        "respect": "Se detectó una expresión de presión." if pressure else "Se detectó una opción o permiso." if permission else "No se detectó presión; falta una opción o permiso explícito.",
        "next_step": f"Acción sugerida: {'detectada' if action else 'no detectada'}; permiso o pregunta: {'detectado' if permission or question else 'no detectado'}.",
    }
    feedback = ["Simulación: la rúbrica usa señales textuales explícitas y puede equivocarse. No mide desempeño real ni sustituye revisión humana."]
    if promise:
        feedback.append("Revisa las promesas o importes detectados y consulta documentación autorizada antes de usar esta respuesta.")
    if pressure:
        feedback.append("Retira la presión detectada y ofrece al cliente decidir con tiempo.")
    if not topic:
        feedback.append("Aborda de forma explícita la inquietud del escenario.")
    if not permission:
        feedback.append("Pide permiso para el siguiente paso y respeta una negativa.")
    return {
        "simulation": True, "method": "explicit_heuristics", "review_required": True,
        "scenario": dict(scenario),
        "rubric": [{**item, "score": scores[item["id"]], "max_score": 2, "evidence": evidence[item["id"]]} for item in RUBRIC],
        "score": sum(scores.values()), "max_score": 12, "feedback": feedback,
    }


def prepare_brief(store, lead_id, actor):
    # Scope is checked before accessing any related record or returning context.
    lead = store.get_lead(lead_id, actor)
    known = [{"label": "Nombre registrado", "value": lead["name"]},
             {"label": "Etapa registrada", "value": lead["stage"]}]
    questions = []
    fields = (("municipality", "Municipio declarado", "¿En qué municipio está el hogar?"),
              ("interest", "Interés declarado", "¿Qué prioridad tiene: consumo, respaldo u otra necesidad?"),
              ("monthly_kwh", "Consumo mensual declarado (kWh)", "¿Cuál es el consumo mensual en kWh de la factura?"),
              ("monthly_bill", "Importe mensual declarado", "¿Desea compartir el importe de su factura, sin datos de cuenta?"))
    for key, label, question in fields:
        value = lead.get(key)
        if value not in (None, ""):
            known.append({"label": label, "value": value})
        else:
            questions.append(question)
    next_actions = []
    if not lead["consent"]:
        next_actions.append("Verificar autorización de contacto antes de iniciar comunicación comercial.")
    if lead.get("next_followup_at"):
        known.append({"label": "Próximo seguimiento registrado", "value": lead["next_followup_at"]})
    appointments = store.list_appointments(actor, lead_id)
    if any(item["status"] == "confirmed" for item in appointments):
        next_actions.append("Revisar las citas confirmadas y verificar los datos con la persona por el canal autorizado.")
    else:
        next_actions.append("Si la persona lo solicita, consultar disponibilidad real para una orientación.")
    next_actions.append("Registrar el resultado de la conversación y acordar el siguiente seguimiento.")
    return {
        "lead_id": lead["id"], "known": known,
        "unverified": ["Los datos declarados no han sido verificados técnicamente por esta herramienta.",
                       "Estado del techo, sombras, cargas críticas, producción, capacidad de respaldo y condiciones contractuales requieren revisión profesional."],
        "questions": questions,
        "topics": ["Diferencia entre potencia (kW) y energía (kWh).",
                   "El respaldo depende del diseño, las cargas y la capacidad de almacenamiento.",
                   "Revisar fuentes y documentos vigentes para productos, garantías y financiación."],
        "next_actions": next_actions, "review_required": True, "certified": False,
    }


def register_routes(app, actor, payload):
    @app.get("/api/assistant/scenarios")
    async def scenarios(user=Depends(actor)):
        return {"scenarios": list(SCENARIOS), "rubric": list(RUBRIC), "simulation": True}

    @app.post("/api/assistant/train")
    async def train(request: Request, user=Depends(actor)):
        app.state.limiter.check(request, "assistant_training", 120, 3600)
        return evaluate_practice(await payload(request))

    @app.get("/api/leads/{lead_id}/brief")
    async def brief(lead_id: str, user=Depends(actor)):
        return prepare_brief(app.state.store, lead_id, user)
