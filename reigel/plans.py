"""Proposed R.E.I.G.E.L. subscription plans, served only to the platform owner.

These are prices for the team's use of R.E.I.G.E.L., not Power Solar products.
They live on the server (not under frontend/, which /static serves publicly) and
no payment processor is connected: nothing here charges anyone.
"""

PLANS = (
    {
        "id": "consultor", "name": "Consultor", "audience": "Un vendedor",
        "monthly_usd": 29, "seats": 1,
        "includes": ["1 licencia de vendedor", "CRM y agenda personal", "Asistente IA con cuota mensual"],
        "note": "No incluye panel del líder.",
    },
    {
        "id": "team_caguas", "name": "Team Caguas", "audience": "Hasta 5 vendedores y 1 líder",
        "monthly_usd": 149, "seats": 5, "extra_seat_usd": 20, "recommended": True,
        "includes": ["CRM y agenda para el equipo", "Panel del líder", "IA compartida con cuota mensual", "Facturación al equipo"],
        "note": "Cada vendedor adicional suma $20/mes hasta que convenga Team Pro.",
    },
    {
        "id": "team_pro", "name": "Team Pro", "audience": "Hasta 15 vendedores y 2 supervisores",
        "monthly_usd": 299, "seats": 15,
        "includes": ["Todo lo de Team Caguas", "Informes avanzados", "Automatizaciones", "Licencias para supervisores"],
        "note": "Sustituye los adicionales cuando el total supera su precio.",
    },
    {
        "id": "corporativo", "name": "Corporativo", "audience": "Varias sucursales",
        "monthly_usd": None, "seats": None,
        "includes": ["Límites negociados", "Soporte e integraciones corporativas", "Revisión de permisos y datos"],
        "note": "Precio por cotización.",
    },
)

NOTICE = ("Precios propuestos, visibles solo para el propietario. No hay una pasarela de pago conectada: "
          "esta vista no cobra, no emite facturas ni suspende cuentas.")


def overview(users):
    active = [user for user in users if user["active"]]
    return {
        "plans": [dict(plan) for plan in PLANS],
        "usage": {
            "advisors": sum(1 for user in active if user["role"] == "advisor"),
            "admins": sum(1 for user in active if user["role"] == "admin"),
            "inactive": sum(1 for user in users if not user["active"]),
        },
        "notice": NOTICE,
    }
