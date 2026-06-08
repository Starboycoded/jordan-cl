# ══════════════════════════════════════════════════════
# JORDAN v5.4 — MODULE REGISTRY
# modules/__init__.py
#
# Every module exposes the same interface:
#   handle(phone, message, button_id, client, session, customer)
#   is_trigger(message, button_id) -> bool
#
# Templates configure WHICH modules are active.
# Modules contain the actual business logic.
# ══════════════════════════════════════════════════════

import json
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# TEMPLATE → MODULE DEFAULTS
# This is the ONLY place templates map to modules.
# No business logic lives here — just on/off flags.
# ─────────────────────────────────────────────────────

TEMPLATE_MODULE_DEFAULTS = {
    # Commerce variants — commerce + support
    "commerce":    {"commerce": True,  "booking": False, "leadgen": False, "support": True},
    "fashion":     {"commerce": True,  "booking": False, "leadgen": False, "support": True},
    "beauty":      {"commerce": True,  "booking": False, "leadgen": False, "support": True},
    "electronics": {"commerce": True,  "booking": False, "leadgen": False, "support": True},
    "food":        {"commerce": True,  "booking": False, "leadgen": False, "support": True},

    # Booking variants — booking + support
    "booking":     {"commerce": False, "booking": True,  "leadgen": False, "support": True},
    "salon":       {"commerce": False, "booking": True,  "leadgen": False, "support": True},
    "clinic":      {"commerce": False, "booking": True,  "leadgen": False, "support": True},

    # Lead gen variants — leadgen + support
    "lead_gen":    {"commerce": False, "booking": False, "leadgen": True,  "support": True},
    "real_estate": {"commerce": False, "booking": False, "leadgen": True,  "support": True},
    "agency":      {"commerce": False, "booking": False, "leadgen": True,  "support": True},

    # Support only
    "support":     {"commerce": False, "booking": False, "leadgen": False, "support": True},

    # General fallback
    "general":     {"commerce": True,  "booking": False, "leadgen": False, "support": True},
}


def get_enabled_modules(client: dict) -> dict:
    """
    Return the active module flags for a client.
    Priority: client.modules_config (DB) > template defaults > general defaults
    """
    template = client.get("template", "general") or "general"
    defaults = TEMPLATE_MODULE_DEFAULTS.get(template, TEMPLATE_MODULE_DEFAULTS["general"])

    # Client-level overrides stored in DB (set by CodedLabs admin)
    override = client.get("modules_config") or {}
    if isinstance(override, str):
        try:
            override = json.loads(override)
        except Exception:
            override = {}

    merged = {**defaults, **override}

    # Support is always available — cannot be disabled
    merged["support"] = True

    return merged


def module_enabled(client: dict, module: str) -> bool:
    """Quick check: is a specific module enabled for this client?"""
    return get_enabled_modules(client).get(module, False)


def validate_tenant(client_id: str, resource_client_id: str) -> bool:
    """
    Strict tenant isolation check.
    Call before returning any resource to verify it belongs to the requesting client.
    Logs a warning on violation — never silently leaks data.
    """
    if str(client_id) != str(resource_client_id):
        logger.warning(
            f"[TENANT VIOLATION] client_id={client_id} attempted to access "
            f"resource belonging to client_id={resource_client_id}"
        )
        return False
    return True
