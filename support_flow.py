# ══════════════════════════════════════════════════════
# JORDAN v5.3 — CUSTOMER SUPPORT FLOW
# For schools, churches, companies, NGOs, government
# Flow: FAQ matching → Claude answers → escalate if needed
# ══════════════════════════════════════════════════════

import logging
import database as db_layer
import whatsapp as wa
import ai_engine as ai

logger = logging.getLogger(__name__)


def handle(phone: str, message: str, button_id: str,
           client: dict, session: dict, customer: dict) -> None:

    client_id = str(client["id"])
    biz_name  = client.get("business_name", "us")
    msg_lower = message.lower().strip()
    btn       = (button_id or "").lower()
    name      = customer.get("name", "")

    # ── BUTTON MAP ──────────────────────────────────
    BMAP = {
        "sp_faqs":   "faqs",
        "sp_hours":  "opening hours",
        "sp_human":  "human",
        "sp_contact":"contact",
    }
    if btn in BMAP:
        message   = BMAP[btn]
        msg_lower = message.lower()

    # ── HUMAN HANDOFF ───────────────────────────────
    if session.get("human_mode"):
        if msg_lower == "resume bot":
            session["human_mode"] = False
            _save(client_id, phone, session)
            wa.send_text(phone, "✅ You're back with Jordan! How can I help?", client)
        else:
            wa.send_text(phone,
                "⚠️ You're connected with our support team. They'll respond shortly.\n"
                "Type *RESUME BOT* to return to the AI assistant.", client)
        return

    if msg_lower in ("human", "agent", "speak to someone", "talk to someone", "sp_human"):
        session["human_mode"] = True
        _save(client_id, phone, session)
        wa.send_text(phone,
            "👤 Connecting you to our support team now.\n"
            "Please hold on — someone will respond shortly.\n\n"
            "Type *RESUME BOT* to return to me anytime.", client)
        from merchant import notify_human_handoff
        import threading
        threading.Thread(
            target=notify_human_handoff,
            args=(phone, message, client),
            daemon=True
        ).start()
        return

    # ── RESET / GREETING ────────────────────────────
    if msg_lower in ("hi", "hello", "hey", "start"):
        greeting = f"Hi{' ' + name if name else ''}! 👋"
        wa.send_buttons(phone,
            f"{greeting} Welcome to *{biz_name}* support.\n\n"
            f"How can I help you today?",
            [{"id": "sp_faqs",   "title": "❓ Common Questions"},
             {"id": "sp_hours",  "title": "🕐 Opening Hours"},
             {"id": "sp_human",  "title": "👤 Talk to Someone"}], client)
        return

    # ── FAQS ────────────────────────────────────────
    if msg_lower in ("faqs", "faq", "common questions", "help"):
        faqs = db_layer.get_faqs(client_id)
        if faqs:
            text = f"❓ *Frequently Asked Questions — {biz_name}*\n\n"
            for i, faq in enumerate(faqs[:8], 1):
                text += f"*{i}. {faq['question']}*\n{faq['answer']}\n\n"
            text += "_Type your question or tap below for more help._"
            wa.send_buttons(phone, text,
                [{"id": "sp_human", "title": "👤 Speak to Someone"}], client)
        else:
            wa.send_text(phone,
                "Our FAQ list is being updated. Ask me anything and I'll do my best to help!", client)
        return

    # ── HOURS ────────────────────────────────────────
    if any(w in msg_lower for w in ("hours", "open", "close", "time", "when")):
        hours = client.get("business_hours", "")
        if hours:
            wa.send_text(phone, f"🕐 *Opening Hours — {biz_name}*\n\n{hours}", client)
        else:
            wa.send_text(phone,
                f"Please contact us directly for our opening hours.\n\n"
                f"Type *CONTACT* for our details.", client)
        return

    # ── CONTACT ─────────────────────────────────────
    if msg_lower in ("contact", "contact us", "phone", "email", "address", "location"):
        contact = client.get("contact_info", "")
        if contact:
            wa.send_text(phone, f"📞 *Contact — {biz_name}*\n\n{contact}", client)
        else:
            wa.send_text(phone,
                f"You're already chatting with us here on WhatsApp! "
                f"Type your question and we'll help. 😊", client)
        return

    # ── AI ANSWER with FAQ context ───────────────────
    faqs    = db_layer.get_faqs(client_id)
    context = session.get("context", [])
    context.append({"role": "user", "content": message})

    # Build support-specific system prompt with FAQ knowledge base
    faq_kb = ""
    if faqs:
        faq_kb = "\nKNOWLEDGE BASE (use this to answer questions accurately):\n"
        for faq in faqs:
            faq_kb += f"Q: {faq['question']}\nA: {faq['answer']}\n\n"

    # Temporarily inject FAQ context into client for AI
    augmented_client = dict(client)
    augmented_client["_faq_context"] = faq_kb

    response, tokens = ai.chat_support(
        message  = message,
        history  = context[:-1],
        client   = augmented_client,
        faqs     = faqs,
        customer = customer
    )

    context.append({"role": "assistant", "content": response})
    session["context"] = context[-20:]
    _save(client_id, phone, session)

    # After AI response, offer escalation
    wa.send_buttons(phone, response,
        [{"id": "sp_human", "title": "👤 Talk to Someone"},
         {"id": "sp_faqs",  "title": "❓ More FAQs"}], client)


def _save(client_id, phone, session):
    import threading
    threading.Thread(
        target=db_layer.save_session,
        args=(client_id, phone, session.get("state", "idle"),
              session.get("cart", {}), session.get("context", []),
              session.get("human_mode", False)),
        daemon=True
    ).start()
