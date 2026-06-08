# ══════════════════════════════════════════════════════
# JORDAN v5.4 — LEAD GENERATION MODULE
# Handles: capture, qualification, pipeline, notifications
# Used by: real_estate, agency, lead_gen templates
# ══════════════════════════════════════════════════════

import logging
import threading

import database as db_layer
import whatsapp as wa
import ai_engine as ai

logger = logging.getLogger(__name__)

DEFAULT_FIELDS = [
    {"key": "name",     "question": "First, what's your name?"},
    {"key": "location", "question": "Where are you based? (city or area)"},
    {"key": "budget",   "question": "Do you have a budget range in mind?"},
    {"key": "timeline", "question": "When are you looking to move forward?"},
    {"key": "interest", "question": "Tell me more about what you're looking for."},
]

ACKS = ["Got it!", "Perfect!", "Great!", "Thanks!", "Noted!"]


def is_trigger(message: str, button_id: str) -> bool:
    msg = message.lower().strip()
    return msg in ("hi", "hello", "hey", "start", "menu", "restart")


def handle(phone: str, message: str, button_id: str,
           client: dict, session: dict, customer: dict) -> None:

    client_id = str(client["id"])
    biz_name  = client.get("business_name", "us")
    msg       = message.lower().strip()
    state     = session.get("state", "idle")
    lead_data = session.get("lead_data", {})

    from templates_config import get_template
    t_cfg  = get_template(client.get("template", "lead_gen"))
    fields = t_cfg.get("lead_fields", DEFAULT_FIELDS)

    # ── RESET ───────────────────────────────────────
    if msg in ("hi", "hello", "hey", "start", "restart", "menu"):
        session["state"]     = "idle"
        session["lead_data"] = {}
        _save(client_id, phone, session)
        greeting = client.get("greeting", "I'd love to understand what you're looking for.")
        wa.send_text(phone,
            f"Hi! 👋 Thanks for reaching out to *{biz_name}*.\n\n{greeting}", client)
        _ask_field(phone, {}, fields, 0, client)
        session["state"] = f"collecting_{fields[0]['key']}"
        _save(client_id, phone, session)
        return

    # ── COLLECTING FIELDS ────────────────────────────
    if state.startswith("collecting_"):
        field_key  = state.replace("collecting_", "")
        lead_data[field_key] = message.strip()
        session["lead_data"] = lead_data

        field_keys  = [f["key"] for f in fields]
        current_idx = field_keys.index(field_key) if field_key in field_keys else -1
        next_idx    = current_idx + 1

        if next_idx < len(fields):
            session["state"] = f"collecting_{fields[next_idx]['key']}"
            _save(client_id, phone, session)
            _ask_field(phone, lead_data, fields, next_idx, client)
        else:
            session["state"] = "lead_complete"
            _save(client_id, phone, session)
            _save_and_notify(phone, lead_data, client, session, customer)
        return

    # ── POST LEAD — AI handles follow-ups ────────────
    if state == "lead_complete":
        context = session.get("context", [])
        context.append({"role": "user", "content": message})

        lead_summary = "\n".join(f"{k}: {v}" for k, v in lead_data.items())
        augmented    = {**client, "_lead_context": lead_summary}

        products = db_layer.get_products(client_id)
        response, tokens = ai.chat(
            message  = message,
            history  = context[:-1],
            client   = augmented,
            products = products,
            customer = customer
        )
        context.append({"role": "assistant", "content": response})
        session["context"] = context[-20:]
        _save(client_id, phone, session)

        if tokens:
            threading.Thread(target=db_layer.log_tokens,
                args=(client_id, tokens), daemon=True).start()

        wa.send_text(phone, response, client)
        return

    # ── IDLE FALLBACK — start collection ────────────
    session["state"]     = f"collecting_{fields[0]['key']}"
    session["lead_data"] = {}
    _save(client_id, phone, session)
    _ask_field(phone, {}, fields, 0, client)


def _ask_field(phone, lead_data, fields, idx, client):
    field    = fields[idx]
    question = field["question"]
    if lead_data and idx > 0:
        question = f"{ACKS[idx % len(ACKS)]} {question}"
    wa.send_text(phone, question, client)


def _save_and_notify(phone, lead_data, client, session, customer):
    client_id = str(client["id"])
    name      = lead_data.get("name", "")

    lead = db_layer.create_lead(
        client_id   = client_id,
        phone       = phone,
        data        = lead_data,
        customer_id = customer.get("id")
    )

    wa.send_text(phone,
        f"Thank you{', ' + name if name else ''}! 🙏\n\n"
        "We've received your details and one of our team members "
        "will be in touch shortly.\n\n"
        "Feel free to ask me any questions in the meantime!", client)

    from merchant import notify_new_lead
    threading.Thread(target=notify_new_lead,
        args=(lead_data, customer, client, None), daemon=True).start()


def _save(client_id, phone, session):
    threading.Thread(
        target=db_layer.save_session,
        args=(client_id, phone, session.get("state", "idle"),
              session.get("cart", {}), session.get("context", []),
              session.get("human_mode", False)),
        daemon=True
    ).start()
