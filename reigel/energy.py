"""Explicit-input arithmetic for preliminary energy orientation, never a quote."""
from __future__ import annotations

import math

from fastapi import Depends, Request

from .core import DomainError


FIELDS = {
    "monthly_kwh", "annual_kwh", "monthly_bill", "panel_watts", "panel_count",
    "system_kw", "specific_yield_kwh_per_kw_year", "coverage_target_percent",
}


def calculate(data):
    if not isinstance(data, dict) or set(data) - FIELDS:
        raise DomainError("Revisa los parámetros de orientación energética.", 422)
    values = {}
    for key, raw in data.items():
        if raw is None or raw == "":
            continue
        try:
            if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
                raise ValueError()
            value = float(raw)
            minimum = 0 if key in {"monthly_kwh", "annual_kwh", "monthly_bill"} else 0.000001
            if not math.isfinite(value) or not minimum <= value <= 1_000_000_000:
                raise ValueError()
            if key == "panel_count" and (not value.is_integer() or value > 1_000_000):
                raise ValueError()
            if key == "coverage_target_percent" and value > 100:
                raise ValueError()
        except (ValueError, TypeError, OverflowError):
            raise DomainError(f"El parámetro {key} debe ser un número finito válido.", 422) from None
        values[key] = int(value) if key == "panel_count" else value

    assumptions, missing = [], []
    monthly, annual = values.get("monthly_kwh"), values.get("annual_kwh")
    if monthly is not None and annual is not None:
        if not math.isclose(monthly * 12, annual, rel_tol=0.001, abs_tol=0.01):
            raise DomainError("El consumo anual y el mensual no coinciden: usa el promedio mensual del mismo periodo o introduce solo el consumo anual.", 422)
    elif monthly is not None:
        annual = monthly * 12
        assumptions.append("Consumo anual = consumo mensual declarado × 12; se supone un mes representativo.")
    elif annual is not None:
        monthly = annual / 12
        assumptions.append("Consumo mensual medio = consumo anual declarado ÷ 12; no describe variaciones estacionales.")
    else:
        missing.append("Consumo mensual medio o anual en kWh; el importe de factura no permite deducirlo sin una tarifa documentada.")

    watts, count, system = values.get("panel_watts"), values.get("panel_count"), values.get("system_kw")
    if watts is not None and count is not None:
        nominal = watts * count / 1000
        if system is not None and not math.isclose(system, nominal, rel_tol=0.001, abs_tol=0.000001):
            raise DomainError("La capacidad del sistema no coincide con la potencia nominal y cantidad de paneles.", 422)
        system = nominal
        assumptions.append("Potencia nominal del arreglo (kW) = potencia de cada panel (W) × cantidad ÷ 1000.")
    if system is None:
        missing.append("Capacidad nominal en kW o potencia documentada de paneles y cantidad.")
    yield_value = values.get("specific_yield_kwh_per_kw_year")
    if yield_value is None:
        missing.append("Rendimiento específico estimado en kWh/kW/año, documentado para el sitio; no se aplica un valor por defecto.")
    production = system * yield_value if system is not None and yield_value is not None else None
    if production is not None:
        assumptions.append("Producción anual estimada = potencia nominal (kW) × rendimiento específico ingresado (kWh/kW/año).")
    coverage = production / annual * 100 if production is not None and annual and annual > 0 else None
    if annual == 0:
        missing.append("Un consumo mayor que cero para calcular el porcentaje de cobertura.")
    target = values.get("coverage_target_percent")
    required_kw = annual * target / 100 / yield_value if annual is not None and annual > 0 and target is not None and yield_value is not None else None
    required_count = math.ceil(required_kw * 1000 / watts) if required_kw is not None and watts is not None else None
    if required_kw is not None:
        assumptions.append("Capacidad preliminar para la cobertura indicada = consumo anual × cobertura objetivo ÷ 100 ÷ rendimiento específico; paneles redondeados hacia arriba.")
    results = {"monthly_kwh": monthly, "annual_kwh": annual, "system_kw": system,
               "system_watts": system * 1000 if system is not None else None,
               "annual_production_kwh": production, "coverage_percent": coverage,
               "required_system_kw": required_kw, "required_panel_count": required_count}
    if any(value is not None and not math.isfinite(value) for value in results.values()):
        raise DomainError("La combinación de parámetros excede el rango numérico de la calculadora.", 422)
    return {
        "results": results,
        "declared": values, "assumptions": assumptions, "missing": missing,
        "limitations": [
            "Orientación matemática preliminar; requiere evaluación profesional del sitio y del diseño.",
            "El rendimiento ingresado debe justificar sombras, orientación, clima, pérdidas y condiciones del sistema; la producción no está garantizada.",
            "La cobertura anual no implica respaldo durante apagones ni independencia de la red; no modela baterías ni simultaneidad de cargas.",
            "La factura es un dato declarado. No se calculan tarifas, ahorros, precios, impuestos ni financiación; no constituye una cotización.",
        ],
        "review_required": True,
    }


def register_routes(app, actor, payload):
    @app.post("/api/energy/calculate")
    async def energy_orientation(request: Request, user=Depends(actor)):
        return calculate(await payload(request))
