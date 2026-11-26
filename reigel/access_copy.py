"""Interface texts that describe how team access is managed.

`/static` is public, so these descriptions do not live in the JavaScript or HTML
files: an authenticated session receives only the block for its role.

- ``member``: any signed-in team account (texts about its own authenticator).
- ``admin``: administrators (issuing one-time codes, offboarding).
- ``owner``: the owner only (allowed emails, naming rule, role help, plans).

This is presentation only. It grants nothing: every action is authorized again
by the server. The repository is public, so this is not secrecy of source code;
it only keeps the deployed site from serving these descriptions to visitors.
"""

from __future__ import annotations

from .team_access import ENV_KEY

MEMBER = {
    "totp_note": ("Es obligatorio para todo el equipo y no se puede desactivar. Al cambiar de teléfono se cierran tus otras "
                  "sesiones. Si pierdes el teléfono, pide a un administrador un código de recuperación."),
    "phone_changed": "Nuevo teléfono registrado en Google Authenticator. Se cerraron tus otras sesiones.",
}

ADMIN = {
    "grant_scope": "Puedes emitir códigos de un solo uso para los asesores del equipo.",
    "grant_purpose_enroll": "Invitación (primer registro)",
    "grant_purpose_recovery": "Recuperación (reemplaza su autenticador)",
    "grant_delivery": ("Entrega este código en persona; no lo envíes por correo ni por chat. Es de un solo uso, vence el "
                       "{expires} y no se volverá a mostrar."),
    "issue_enroll_intro": "todavía no tiene Google Authenticator. Con su contraseña y este código podrá registrarlo en su primer acceso.",
    "issue_recovery_intro": "ya tiene Google Authenticator. Este código le permite registrar un teléfono nuevo y cierra sus sesiones abiertas.",
    "issue_once": "El código se muestra una sola vez. Emitir uno nuevo anula el anterior.",
    "issue_result": "Código de un solo uso para",
    "issue_steps_enroll": [
        "Entrégalo en persona. No lo envíes por correo, chat ni capturas de pantalla.",
        "La persona entra en /app con su correo y contraseña y escribe este código cuando se le pida.",
        "Si se pierde o vence, emite otro: el anterior deja de servir.",
    ],
    "issue_steps_recovery": [
        "Entrégalo en persona. No lo envíes por correo, chat ni capturas de pantalla.",
        "La persona entra en /app con su correo y contraseña y, en /app/acceso, escribe este código para registrar el teléfono nuevo.",
        "Si se pierde o vence, emite otro: el anterior deja de servir.",
    ],
    "offboard_notice": ("La cuenta pierde el acceso en este momento: se cierran sus sesiones y no podrá volver a entrar. Sus "
                        "prospectos, citas pendientes, tareas y conversaciones pasan a la persona que elijas. No se borra ningún registro."),
}

# The owner also issues codes for administrators; an administrator is not told so.
OWNER_ADMIN = ADMIN | {
    "grant_scope": ("Un administrador emite códigos solo para asesores; solo el propietario los emite para administradores. "
                    "Los códigos del propietario se obtienen en el servidor."),
}

OWNER = {
    "panel_kicker": "SOLO PROPIETARIO · SEGURIDAD DE ACCESO",
    "panel_title": "Correos autorizados",
    "panel_help": ("Solo estos correos pueden tener cuenta en R.E.I.G.E.L. y entrar. Google Authenticator es obligatorio para "
                   "todas las cuentas, sin excepciones. Quitar un correo cierra sus sesiones en ese momento. Tu cuenta de "
                   "propietario no se puede quitar."),
    "sources": {"env": f"Desde {ENV_KEY}", "owner": "Añadido por el propietario", "owner_account": "Cuenta del propietario"},
    "status_blocked": "No cumple la regla «Power Solar»",
    "status_no_account": "Sin cuenta todavía",
    "status_inactive": "Cuenta dada de baja",
    "status_enrolled": "Google Authenticator activo",
    "status_pending": "Registrará Google Authenticator al entrar",
    "empty": "No hay correos en la lista.",
    "allow_label": "Autorizar un correo",
    "allow_placeholder": "nombre.powersolar@empresa.com",
    "allow_button": "Autorizar correo",
    "allow_done": "Correo autorizado. La persona registrará Google Authenticator en su primer acceso.",
    "rule_kicker": "REGLA «POWER SOLAR»",
    "rule_on_label": "Activa.",
    "rule_on_text": "Cada correo autorizado debe contener «powersolar» en el nombre o en el dominio.",
    "rule_off_label": "Desactivada.",
    "rule_off_text": "Se acepta cualquier correo que esté en la lista.",
    "rule_disable": "Desactivar la regla",
    "rule_enable": "Activar la regla",
    "rule_disabled_done": "Regla «Power Solar» desactivada.",
    "rule_enabled_done": "Regla «Power Solar» activada. Se cerraron las sesiones de las cuentas que no la cumplen.",
    "remove_title": "Quitar correo autorizado",
    "remove_before": "Se quitará",
    "remove_after": ("de la lista. Si tiene una cuenta, sus sesiones se cerrarán ahora y no podrá volver a entrar hasta que "
                     "autorices el correo otra vez. No se borra ningún registro."),
    "remove_button": "Quitar correo",
    "remove_done": "Correo quitado. Sus sesiones se cerraron.",
    "role_help": "Un administrador gestiona asesores y ajustes; no ve la suscripción ni puede dar de baja a otros administradores.",
    "subscription_kicker": "SOLO PROPIETARIO",
    "subscription_intro": ("Planes propuestos para el uso de R.E.I.G.E.L. por tu equipo. No los ven los administradores, "
                           "los asesores ni los clientes."),
    "policy_note": "Gestiona quién forma parte del equipo en «Equipo y ajustes».",
}


def copy_for(user) -> dict:
    """Texts for the caller's role. An advisor receives no administration or owner text."""
    copy = {"member": dict(MEMBER)}
    if user and user.get("role") == "admin":
        owner = bool(user.get("is_owner"))
        copy["admin"] = dict(OWNER_ADMIN if owner else ADMIN)
        if owner:
            copy["owner"] = dict(OWNER)
    return copy


def strings(value) -> list[str]:
    """Every text in a block, flattened (used by the tests that scan the static files)."""
    if isinstance(value, str):
        return [value]
    items = value.values() if isinstance(value, dict) else value
    return [text for item in items for text in strings(item)]
