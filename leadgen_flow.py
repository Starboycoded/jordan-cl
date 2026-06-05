# ══════════════════════════════════════════════════════
# JORDAN v5.3 — LEAD GENERATION FLOW
# For real estate, insurance, agencies, solar, digital marketing
# Flow: greeting → collect fields → qualify → save lead → notify merchant
# ══════════════════════════════════════════════════════

import logging
import database as db_layer
import whatsapp as wa
import ai_engine as ai

logger = logging.getLogger(__name__)


def handle(phone: str, message: str, button_id: str,
           client: dict, session: dict, customer: dict) -> None:

    client_id  = str(client["id"])
    biz_name   = client.get("business_name", "us")
    msg_lower  = message.lower().strip()
    btn        = (button_id or "").lower()
    state      = session.get("state", "idle")
    lead_data  = session.get("lead_data", {})
    name       = customer.get("name") or lead_data.get("name", "")

    from templates_config import get_template
    t_cfg      = get_template(client.get("template", "lead_gen"))
    fields     = t_cfg.get("lead_fields", _default_fields())

    # ── RESET ───────────────────────────────────────
    if msg_lower in ("hi", "hello", "hey", "start", "restart"):
        session["state"]     = "idle"
        session["lead_data"] = {}
        _save(client_id, phone, session)
        wa.send_text(phone,
            f"Hi! 👋 Thanks for reaching out to *{biz_name}*.\n\n"
            f"{client.get('greeting', 'I\'d love to understand what you\'re looking for.')}", client)
        _ask_next_field(phone, {}, fields, 0, client)
        return

    # ── HUMAN REQUEST ───────────────────────────────
    if msg_lower in ("human", "agent", "speak to someone", "talk to someone"):
        session["human_mode"] = True
        _save(client_id, phone, session)
        wa.send_text(phone,
            "👤 I'm connecting you to one of our team members now. "
            "They'll be with you shortly!", client)
        from merchant import notify_new_lead
        import threading
        threading.Thread(
            target=notify_new_lead,
            args=(lead_data, customer, client, "Human handoff requested"),
            daemon=True
        ).start()
        return

    # ── STATE MACHINE: collecting fields ────────────
    if state.startswith("collecting_"):
        field_key = state.replace("collecting_", "")
        lead_data[field_key] = message.strip()
        session["lead_data"] = lead_data

        # Find which field index we just completed
        field_keys = [f["key"] for f in fields]
        if field_key in field_keys:
            current_idx = field_keys.index(field_key)
            next_idx    = current_idx + 1

            if next_idx < len(fields):
                # Ask next field
                session["state"] = f"collecting_{fields[next_idx]['key']}"
                _save(client_id, phone, session)
                _ask_next_field(phone, lead_data, fields, next_idx, client)
            else:
                # All fields collected — save lead
                session["state"] = "lead_complete"
                _save(client_id, phone, session)
                _save_and_notify(phone, lead_data, client, session, customer)
        return

    # ── IDLE: start collection ───────────────────────
    if state == "idle":
        session["state"]     = f"collecting_{fields[0]['key']}"
        session["lead_data"] = {}
        _save(client_id, phone, session)
        _ask_next_field(phone, {}, fields, 0, client)
        return

    # ── POST-LEAD ────────────────────────────────────
    if state == "lead_complete":
        # Use AI to handle follow-up questions naturally
        context  = session.get("context", [])
        context.append({"role": "user", "content": message})

        lead_summary = "\n".join(f"{k}: {v}" for k, v in lead_data.items())
        extra_system = (
            f"\nLEAD ALREADY CAPTURED:\n{lead_summary}\n\n"
            f"The customer's information has been saved. "
            f"Now answer any follow-up questions they have. "
            f"If they want to change something, collect it again. "
            f"Be helpful and professional."
        )
        products = db_layer.get_products(client_id)
        response, tokens = ai.chat(
            message  = message,
            history  = context[:-1],
            client   = client,
            products = products,
            customer = customer
        )
        context.append({"role": "assistant", "content": response})
        session["context"] = context[-20:]
        _save(client_id, phone, session)
        wa.send_text(phone, response, client)
        return

    # ── FALLBACK ────────────────────────────────────
    wa.send_text(phone,
        f"Hi! 👋 I'm here to help you with *{biz_name}*. "
        f"Type *HI* to get started!", client)


# ─────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────

def _default_fields() -> list:
    return [
        {"key": "name",     "question": "First, what's your name?"},
        {"key": "location", "question": "Where are you based? (city or area)"},
        {"key": "budget",   "question": "Do you have a budget range in mind?"},
        {"key": "interest", "question": "Tell me more about what you're looking for."},
    ]


def _ask_next_field(phone: str, lead_data: dict, fields: list,
                    idx: int, client: dict):
    field    = fields[idx]
    question = field["question"]

    # Personalize if we have their name
    name = lead_data.get("name", "")
    if name and idx > 0:
        # Light acknowledgement on first answer
        acks = ["Got it!", "Perfect!", "Great!", "Thanks!"]
        question = f"{acks[idx % len(acks)]} {question}"

    wa.send_text(phone, question, client)


def _save_and_notify(phone: str, lead_data: dict, client: dict,
                     session: dict, customer: dict):
    client_id = str(client["id"])

    # Save lead to DB
    lead = db_layer.create_lead(
        client_id   = client_id,
        phone       = phone,
        data        = lead_data,
        customer_id = customer.get("id")
    )

    # Thank the customer
    name = lead_data.get("name", "")
    wa.send_text(phone,
        f"Thank you{', ' + name if name else ''}! 🙏\n\n"
        f"We've received your information and one of our team members "
        f"will be in touch with you shortly.\n\n"
        f"In the meantime, feel free to ask me any questions!", client)

    # Notify merchant
    from merchant import notify_new_lead
    import threading
    threading.Thread(
        target=notify_new_lead,
        args=(lead_data, customer, client, None),
        daemon=True
    ).start()


def _save(client_id, phone, session):
    import threading
    threading.Thread(
        target=db_layer.save_session,
        args=(client_id, phone, session.get("state", "idle"),
              session.get("cart", {}), session.get("context", []),
              session.get("human_mode", False)),
        daemon=True
    ).start()
