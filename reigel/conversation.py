"""Deterministic intent decisions for the public Spanish-language chat.

This module classifies customer text only. It never executes actions, accesses
customer records, or treats user text as trusted instructions.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IntentDecision:
    intent: str
    confidence: float
    entities: dict[str, Any] = field(default_factory=dict)
    missing: tuple[str, ...] = ()
    action: str = "respond"


def normalize(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )


_AMOUNT = r"\d{1,5}(?:[.,]\d{1,2})?"
_BILL_AMOUNT = re.compile(
    rf"(?:factura(?:\s+(?:es\s+de|de|es))?|pago|mensual(?:es)?(?:\s+(?:es|de))?|al mes|\$)"
    rf"\s*\$?\s*({_AMOUNT})\b"
)
_BILL_AMOUNT_TRAILING = re.compile(
    rf"(?<!\w)\$?({_AMOUNT})\s*(?:dolares|al mes|mensual(?:es)?)\b"
)
_MONTHLY_BILL_ANSWER = re.compile(
    rf"\s*(?:(?:son|serian|pago|es)\s*)?"
    rf"(?:(?:unos?|aproximadamente|aprox\.?)\s*)?"
    rf"\$?\s*{_AMOUNT}\s*(?:dolares|al mes|mensual(?:es)?)?\s*"
)
_CORRECTION = re.compile(
    r"\b(?:quise decir|queria decir|me equivoque|en realidad|corrijo|"
    r"mejor dicho|no,?\s*(?:es|son|pago|mi factura))\b"
)
_FINANCIAL = re.compile(
    r"\b(?:financi\w*|credito|prestamo|mensualidad|cuota|interes)\b"
)
_TECHNICAL_QUESTION = re.compile(
    r"\b(?:kw|kwh|kilovatios?|kilowat\w*|microinversor\w*|inversor\w*|"
    r"fotovoltaic\w*|paneles solares|placas solares|medicion neta|net metering|"
    r"sistema hibrid\w*|sistema interconectado|conectado a la red|on.?grid|"
    r"eficiencia(?: energetica)?|produccion solar|produccion fotovoltaica|generacion solar|"
    r"dimensionamiento|dimensionar|vida util|mantenimiento preventivo|"
    r"seguridad electrica)\b"
)

_UNSUPPORTED_COMMERCIAL = re.compile(
    r"\b(?:precio\w*|cuanto cuesta|cuanto sale|oferta\w*|"
    r"promocion\w*|descuento\w*|incentivo\w*|garantia\w*|"
    r"ahorr\w*|costo\w*|gratis|pagar con tarjeta|"
    r"aceptan? tarjetas?|reciben tarjetas?|"
    r"tarjetas? de (?:credito|debito))\b"
)

_OPT_OUT = re.compile(
    r"\b(?:darme de baja|darme la baja|dejen? de (?:escribir|contactar)|"
    r"no me (?:contact\w*|escrib\w*|llam\w*)|"
    r"no (?:quiero|deseo) (?:recibir )?(?:mas )?mensajes|"
    r"no mas mensajes)\b"
)

_PRIVACY_DELETION = re.compile(
    r"\b(?:elimin\w*|borr\w*|suprim\w*)\b.{0,45}\bmis (?:datos|registros|informacion)\b|"
    r"\b(?:eliminacion|borrado|supresion) de mis datos\b"
)
_PRIVACY_ACCESS = re.compile(
    r"\b(?:acced\w*|acceso|consult\w*|copi\w*|export\w*|ver)\b.{0,45}\bmis datos\b|"
    r"\bque (?:datos|informacion) (?:tienen|guardan|conservan) (?:sobre|de) mi\b"
)
_PRIVACY_CORRECTION = re.compile(
    r"\b(?:correg\w*|corrig\w*|rectific\w*|actualiz\w*)\b.{0,45}\bmis (?:datos|registros|informacion)\b|"
    r"\b(?:correg\w*|corrig\w*|rectific\w*)\b.{0,30}\bmi (?:nombre|telefono|correo)\b"
)


def _decision(
    intent: str,
    confidence: float,
    action: str,
    *,
    entities: dict[str, Any] | None = None,
    missing: tuple[str, ...] = (),
) -> IntentDecision:
    return IntentDecision(intent, confidence, entities or {}, missing, action)


def classify_message(
    message: str,
    *,
    context: dict[str, Any] | None = None,
) -> IntentDecision:
    """Return a testable, conservative decision for a single customer message."""
    if not isinstance(message, str) or not message.strip():
        return _decision("ambiguous", 0.0, "clarify", missing=("intent",))

    value = normalize(message).strip()
    context = context or {}

    if value == "/start":
        return _decision("resume", 1.0, "resume_assistance")
    # A communications opt-out and a data-rights request have different effects.
    # These patterns require first-person data; they never authorize another
    # person's record lookup or an automatic deletion.
    for pattern, kind in ((_PRIVACY_DELETION, "deletion"), (_PRIVACY_ACCESS, "access"), (_PRIVACY_CORRECTION, "correction")):
        if pattern.search(value):
            return _decision("privacy_request", 0.98, "register_privacy_request", entities={"request_kind": kind})
    if value in {"/stop", "stop", "baja", "detener", "parar", "salir", "unsubscribe", "cancelar mensajes"} or _OPT_OUT.search(value):
        return _decision("opt_out", 1.0, "stop_assistance")
    
    # --- CAMBIO APLICADO AQUÍ ---
    if re.search(
        r"\b(?:ignora|ignorar|instrucciones|system prompt|prompt|sql|"
        r"contrasena|cuenta bancaria|datos de otro cliente|"
        r"(?:datos|numero|cvv|codigo)\s+"
        r"(?:de\s+)?(?:mi\s+|la\s+)?tarjeta)\b",
        value,
    ):
        return _decision("safety", 0.98, "safe_redirect")
    # ----------------------------

    if re.search(r"\b(?:humano|humana|una persona|un representante|"
                 r"hablar con (?:un |una )?asesor|quiero (?:un |una )?asesor)\b", value):
        return _decision("human", 0.98, "handoff")
    if re.search(r"\b(?:cancelar|cancela|cambiar|reprogramar|mover)\b.*"
                 r"\b(?:cita|reserva|horario)\b|\b(?:cita|reserva)\b.*"
                 r"\b(?:cancelar|reprogramar|cambiar)\b", value):
        return _decision("appointment_change", 0.96, "handoff")
    if re.search(r"\b(?:no me interesa|no estoy interesado|no estoy interesada|"
                 r"no quiero seguir|no deseo continuar|no gracias)\b", value):
        return _decision("decline", 0.95, "respect_decline")
    if re.search(r"\b(?:reserva|reservar|agend\w*|coordinar|horarios?|"
                 r"cita|evaluacion)\b", value):
        return _decision(
            "booking",
            0.93,
            "propose_booking",
            missing=("advisor", "available_time", "contact", "consent"),
        )
    if _CORRECTION.search(value):
        amount_matches = list(_BILL_AMOUNT.finditer(value))
        entities = {}
        if amount_matches:
            entities["bill_amount"] = float(
                amount_matches[-1].group(1).replace(",", ".")
            )
        else:
            trailing_amount = _BILL_AMOUNT_TRAILING.search(value)
            if trailing_amount:
                entities["bill_amount"] = float(
                    trailing_amount.group(1).replace(",", ".")
                )
        return _decision(
            "correction",
            0.82 if entities else 0.72,
            "update_session_fact" if entities else "clarify",
            entities=entities,
            missing=() if entities else ("corrected_fact",),
        )
    if re.search(r"\b(?:factura|pago|mensual|al mes)\b", value):
        amounts = list(_BILL_AMOUNT.finditer(value))
        has_correction = _CORRECTION.search(value)
        if len(amounts) > 1 and not has_correction:
            return _decision(
                "contradiction",
                0.88,
                "clarify",
                entities={
                    "bill_amounts": [
                        float(match.group(1).replace(",", "."))
                        for match in amounts
                    ]
                },
                missing=("confirmed_bill_amount",),
            )
    if context.get("last_question") == "bill_period":
        if re.search(r"\b(?:anual|por ano|cada ano)\b", value):
            return _decision("bill_uncertain", 0.8, "clarify", missing=("bill_period",))
        monthly_denial = re.search(
            r"\bno(?:\s+es)?\s+(?:mensual|al mes|por mes|cada mes)\b", value
        )
        if not monthly_denial and re.search(
            r"\b(?:si|mensual|al mes|por mes|cada mes)\b", value
        ):
            return _decision("bill_confirmation", 0.94, "confirm_session_fact")
    if context.get("last_question") == "monthly_bill" and _MONTHLY_BILL_ANSWER.fullmatch(value):
        amount = float(re.search(_AMOUNT, value).group().replace(",", "."))
        return _decision(
            "bill_answer",
            0.91,
            "update_session_fact",
            entities={"bill_amount": amount, "bill_period": "monthly"},
        )
    if re.search(r"\b(?:ya tengo|tengo|instale)\b.*\b(?:placas|paneles|sistema solar)\b|"
                 r"\b(?:sistema|paneles|placas)\b.*\b(?:averia|no funciona|reparacion)\b", value):
        return _decision("existing_system", 0.91, "handoff")
    if re.search(r"\b(?:mantenimiento|servicio tecnico|reparacion|averia|falla electrica)\b", value):
        return _decision("maintenance", 0.9, "handoff")
    if re.search(r"\b(?:garantiz\w*|garantia)\b", value) and re.search(
        r"\b(?:ahorr\w*|factura|produc\w*|resultado)\b", value
    ):
        return _decision("guaranteed_savings", 0.94, "decline_unsupported_claim")
    if _FINANCIAL.search(value):
        return _decision("financing", 0.9, "explain_unverified_terms")
    if _UNSUPPORTED_COMMERCIAL.search(value):
        return _decision("commercial_terms", 0.9, "explain_unverified_terms")
    if "luma" in value and re.search(r"\b(?:factura|recibo|cargo|tarifa)\b", value) and not re.search(
        r"\bconsumo\b", value
    ):
        return _decision("technical_question", 0.88, "retrieve_knowledge")
    if re.search(r"\b(?:caro|costoso|presupuesto|no puedo pagar|no tengo dinero)\b", value):
        return _decision("budget_objection", 0.88, "respond_without_pressure")
    if re.search(r"\b(?:desconfio|confio|estafa|engan\w*|riesgo|seguridad|"
                 r"no creo|tengo dudas)\b", value):
        return _decision("trust_objection", 0.86, "respond_with_verifiable_steps")
    if re.search(r"\b(?:pensarlo|voy a pensar|no estoy listo|despues|luego|otro momento)\b", value):
        return _decision("defer", 0.92, "respect_decline")
    if re.search(r"\b(?:apagon(?:es)?|bateria(?:s)?|respaldo)\b", value):
        return _decision(
            "backup",
            0.9,
            "collect_information",
            missing=("backup_loads", "system_design"),
        )
    if context.get("last_question") == "bill_period" and re.search(
        r"\b(?:no|anual|por ano|no se|no estoy seguro)\b", value
    ):
        return _decision("bill_uncertain", 0.8, "clarify", missing=("bill_period",))
    if re.search(
        r"\b(?:kw\s*(?:y|vs\.?|versus)\s*kwh|kwh\s*(?:y|vs\.?|versus)\s*kw|"
        r"diferencia.{0,30}\bkw\b|\bkw\b.{0,30}\bkwh\b|"
        r"(?:que es|significa)\s*(?:un\s*)?kwh)\b",
        value,
    ):
        return _decision("technical_question", 0.88, "retrieve_knowledge")
    if re.search(r"\b(?:no se|desconozco|no conozco)\b.*\b(?:kwh|consumo)\b|"
                 r"\b(?:kwh|consumo)\b", value):
        return _decision(
            "consumption",
            0.78,
            "explain_information_needed",
            missing=("energy_usage",),
        )
    if re.search(r"\b(?:hola|buenas|saludos|buenos dias|buenas tardes)\b", value):
        return _decision("greeting", 0.95, "continue_conversation")
    if re.search(r"\b(?:empresa|quienes son|quien es|power solar|tienda|"
                 r"ubicacion|direccion|localizacion|proceso|instalacion|"
                 r"servicio|producto|solucion|apartamento|comercial|negocio|"
                 r"ofrecen|venden|visita tecnica|interconexion)\b", value):
        return _decision("company_information", 0.82, "retrieve_knowledge")
    if _TECHNICAL_QUESTION.search(value) and not re.search(
        r"\b(?:consumo|factura|pago|no se|desconozco|cuanto pago)\b", value
    ):
        return _decision("technical_question", 0.88, "retrieve_knowledge")
    if context.get("last_question") in {"loads", "monthly_bill", "bill_period", "priority", "municipality"}:
        return _decision(
            "contextual_follow_up",
            0.55,
            "clarify",
            missing=(str(context["last_question"]),),
        )
    return _decision("unsupported_or_ambiguous", 0.3, "clarify", missing=("intent",))
