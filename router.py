# ══════════════════════════════════════════════════════
# JORDAN v5.4 — MESSAGE ROUTER
# Single entry point for all incoming messages.
# Routes to enabled modules based on client config.
#
# Order of precedence:
#   1. Support (universal — always checked first)
#   2. Commerce (if enabled)
#   3. Booking  (if enabled)
#   4. Lead Gen (if enabled)
#   5. AI fallback
# ══════════════════════════════════════════════════════

import logging
import threading

import database as db_layer
import whatsapp as wa
import ai_engine as ai
from modules import get_enabled_modules, module_enabled

from modules import support  as support_mod
from modules import commerce as commerce_mod
from modules import booking  as booking_mod
from modules import leadgen  as leadgen_mod

logger = logging.getLogger(__name__)

# Session TTL in seconds (1 hour)
SESSION_TTL = 3600


def route(phone: str, message: str, button_id: str,
          client: dict, session: dict, customer: dict) -> None:
    """
    Route an incoming message to the correct module(s).
    This is the ONLY function core_system.py calls after
    merchant checks and session setup.
    """
    modules   = get_enabled_modules(client)
    client_id = str(client["id"])

    # ── 1. SUPPORT — always first, always available ──
    # Intercepts: FAQ, human handoff, contact, hours, complaints
    if support_mod.is_trigger(message, button_id) or \
       session.get("state") == "reporting_issue" or \
       session.get("human_mode"):
        handled = support_mod.handle(phone, message, button_id, client, session, customer)
        if handled:
            return

    # ── 2. COMMERCE MODULE ───────────────────────────
    # Skip commerce if customer is mid-booking (prevents checkout hijacking)
    booking_states = ("awaiting_date", "awaiting_time", "awaiting_notes", "confirm_booking")
    if modules.get("commerce") and session.get("state") not in booking_states:
        if commerce_mod.is_trigger(message, button_id) or \
           session.get("state") in ("awaiting_address", "confirm_order", "confirm_clear"):
            commerce_mod.handle(phone, message, button_id, client, session, customer)
            return

    # ── 3. BOOKING MODULE ────────────────────────────
    if modules.get("booking"):
        if booking_mod.is_trigger(message, button_id) or \
           session.get("state") in ("awaiting_date", "awaiting_time", "awaiting_notes", "confirm_booking"):
            booking_mod.handle(phone, message, button_id, client, session, customer)
            return

    # ── 4. LEAD GEN MODULE ───────────────────────────
    if modules.get("leadgen"):
        if leadgen_mod.is_trigger(message, button_id) or \
           session.get("state", "").startswith("collecting_") or \
           session.get("state") == "lead_complete":
            leadgen_mod.handle(phone, message, button_id, client, session, customer)
            return

    # ── 5. FALLBACK ─────────────────────────────────
    # No module matched. Let Claude handle it with context
    # about what modules this client has available.
    _fallback(phone, message, client, session, customer, modules)


def _fallback(phone, message, client, session, customer, modules):
    """
    AI response when no module explicitly handles the message.
    Gives Claude context about what this business can do.
    """
    client_id = str(client["id"])
    products  = db_layer.get_products(client_id)
    context   = session.get("context", [])
    context.append({"role": "user", "content": message})

    # Build a capability hint for the AI
    caps = []
    if modules.get("commerce"): caps.append("selling products")
    if modules.get("booking"):  caps.append("booking appointments")
    if modules.get("leadgen"):  caps.append("capturing enquiries")
    caps.append("answering questions")

    augmented = {**client, "_capabilities": ", ".join(caps)}

    response, tokens = ai.chat(
        message  = message,
        history  = context[:-1],
        client   = augmented,
        products = products,
        customer = customer
    )
    context.append({"role": "assistant", "content": response})
    session["context"] = context[-20:]

    threading.Thread(
        target=db_layer.save_session,
        args=(client_id, phone, session.get("state", "idle"),
              session.get("cart", {}), context[-20:],
              session.get("human_mode", False)),
        daemon=True
    ).start()

    if tokens:
        threading.Thread(target=db_layer.log_tokens,
            args=(client_id, tokens), daemon=True).start()

    wa.send_text(phone, response, client)
