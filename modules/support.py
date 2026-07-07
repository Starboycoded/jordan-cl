# ══════════════════════════════════════════════════════
# JORDAN v5.4 — SUPPORT MODULE
# Universal — active for EVERY client regardless of template.
# Handles: FAQ, human handoff, contact info, issue tickets
# Always runs FIRST before any other module.
# ══════════════════════════════════════════════════════

import logging
import threading

import database as db_layer
import whatsapp as wa
import ai_engine as ai

logger = logging.getLogger(__name__)

SUPPORT_TRIGGERS = frozenset([
    "help", "support", "faq", "faqs", "questions",
    "contact", "contact us", "phone number", "email",
    "opening hours", "hours", "location", "address",
    "directions", "find you", "where are you",
])

HUMAN_TRIGGERS = frozenset([
    "human", "agent", "person", "real person",
    "speak to someone", "talk to someone",
    "speak to agent", "customer service",
    "i need help", "urgent",
])

ISSUE_TRIGGERS = frozenset([
    "complaint", "complain", "problem", "issue",
    "wrong", "mistake", "error", "not working",
])

BUTTON_MAP = {
    "sp_faq":     "faq",
    "sp_hours":   "opening hours",
    "sp_contact": "contact",
    "sp_human":   "human",
    "sp_report":  "report issue",
}


def is_trigger(message: str, button_id: str) -> bool:
    btn = (button_id or "").lower()
    msg = message.lower().strip()
    if btn in BUTTON_MAP:
        return True
    if msg in SUPPORT_TRIGGERS | HUMAN_TRIGGERS | ISSUE_TRIGGERS:
        return True
    for trigger in HUMAN_TRIGGERS | ISSUE_TRIGGERS:
        if trigger in msg:
            return True
    return False


def handle(phone: str, message: str, button_id: str,
           client: dict, session: dict, customer: dict) -> bool:
    """
    Handle support messages.
    Returns True if handled (caller should stop routing).
    Returns False if not a support message.
    """
    client_id = str(client["id"])
    biz_name  = client.get("business_name", "us")
    btn       = (button_id or "").lower()
    msg       = message.lower().strip()

    # Remap buttons
    if btn in BUTTON_MAP:
        msg = BUTTON_MAP[btn]

    # ── RESUME BOT ──────────────────────────────────
    if msg == "resume bot" and session.get("human_mode"):
        session["human_mode"] = False
        _save(client_id, phone, session)
        wa.send_text(phone, "✅ You're back with Jordan! How can I help?", client)
        return True

    # ── HUMAN MODE ACTIVE (v5.6 — relay to merchant) ──
    if session.get("human_mode"):
        merchant_phone = (client.get("merchant_phone") or "").strip()
        if merchant_phone:
            wa.send_text(merchant_phone,
                f"📩 *Customer +{phone}:* {message}\n\n"
                "_Reply here to respond. Type RESUME to end._", client)
            wa.send_text(phone,
                "✅ Message sent to the team. They'll respond shortly.\n"
                "_Type *RESUME BOT* to return to Jordan._", client)
        else:
            wa.send_text(phone,
                "⚠️ You're connected with our team. They'll respond shortly.\n"
                "_Type *RESUME BOT* to return to Jordan._", client)
        return True
    # ── HUMAN HANDOFF REQUEST ────────────────────────
    if msg in HUMAN_TRIGGERS or any(t in msg for t in HUMAN_TRIGGERS):
        session["human_mode"] = True
        _save(client_id, phone, session)
        wa.send_text(phone,
            f"👤 Connecting you to the *{biz_name}* team.\n\n"
            "Please hold — someone will respond shortly.\n\n"
            "_Type *RESUME BOT* to return to the AI assistant._", client)
        from merchant import notify_human_handoff
        threading.Thread(target=notify_human_handoff, args=(phone, message, client), daemon=True).start()
        return True

    # ── COLLECTING ISSUE REPORT ──────────────────────
    if session.get("state") == "reporting_issue":
        issue_text = message.strip()
        session["state"] = "idle"
        _save(client_id, phone, session)
        _save_issue(customer, issue_text)
        wa.send_text(phone,
            "✅ Issue logged. The *" + biz_name + "* team will follow up.\n\n"
            "_Is there anything else I can help with?_", client)
        from merchant import notify_human_handoff
        threading.Thread(target=notify_human_handoff,
            args=(phone, f"ISSUE REPORT: {issue_text}", client), daemon=True).start()
        return True

    # ── ISSUE / COMPLAINT ────────────────────────────
    if msg in ISSUE_TRIGGERS or any(t in msg for t in ISSUE_TRIGGERS):
        session["state"] = "reporting_issue"
        _save(client_id, phone, session)
        wa.send_text(phone,
            "I'm sorry to hear that. 😔\n\n"
            "Please describe the issue in detail and I'll make sure the team sees it.", client)
        return True

    # ── FAQ ─────────────────────────────────────────
    if msg in ("faq", "faqs", "questions", "common questions"):
        faqs = db_layer.get_faqs(client_id)
        if not faqs:
            wa.send_text(phone,
                "Our FAQ list isn't set up yet. Ask me anything and I'll do my best to help!", client)
            return True
        text = f"❓ *Common Questions — {biz_name}*\n\n"
        for i, faq in enumerate(faqs[:8], 1):
            text += f"*{i}. {faq['question']}*\n{faq['answer']}\n\n"
        text += "_Type your question for more help._"
        wa.send_buttons(phone, text,
            [{"id": "sp_human", "title": "👤 Talk to Someone"}], client)
        return True

    # ── OPENING HOURS ────────────────────────────────
    if any(w in msg for w in ("hours", "open", "close", "when are you", "opening")):
        hours = (client.get("business_hours") or "").strip()
        if hours:
            wa.send_text(phone, f"🕐 *Opening Hours — {biz_name}*\n\n{hours}", client)
        else:
            wa.send_buttons(phone, "Opening hours haven't been set yet. Contact us directly.",
                [{"id": "sp_human",   "title": "👤 Contact Us"},
                 {"id": "sp_contact", "title": "📞 Get Info"}], client)
        return True

    # ── CONTACT INFO ─────────────────────────────────
    if any(w in msg for w in ("contact", "phone number", "email", "address", "location", "directions")):
        contact = (client.get("contact_info") or "").strip()
        if contact:
            wa.send_text(phone, f"📞 *Contact — {biz_name}*\n\n{contact}", client)
        else:
            wa.send_text(phone,
                "You're already chatting with us here! Type your question and we'll help. 😊", client)
        return True

    # ── AI FAQ ANSWER (Premium feature) ─────────────
    from subscriptions import can
    if can(client, "ai_faq_kb"):
        faqs    = db_layer.get_faqs(client_id)
        context = session.get("context", [])
        context.append({"role": "user", "content": message})
        response, tokens = ai.chat_support(
            message=message, history=context[:-1],
            client=client, faqs=faqs, customer=customer
        )
        context.append({"role": "assistant", "content": response})
        session["context"] = context[-20:]
        _save(client_id, phone, session)
        if tokens:
            threading.Thread(target=db_layer.log_tokens, args=(client_id, tokens), daemon=True).start()
        wa.send_buttons(phone, response,
            [{"id": "sp_human", "title": "👤 Talk to Someone"},
             {"id": "sp_faq",   "title": "❓ More FAQs"}], client)
        return True

    return False


def _save_issue(customer, issue_text):
    try:
        if customer.get("id"):
            db_layer.db().table("customers").update({
                "notes": f"Issue: {issue_text[:500]}"
            }).eq("id", customer["id"]).execute()
    except Exception as e:
        logger.error(f"[Support] _save_issue: {e}")


def _save(client_id, phone, session):
    threading.Thread(
        target=db_layer.save_session,
        args=(client_id, phone, session.get("state", "idle"),
              session.get("cart", {}), session.get("context", []),
              session.get("human_mode", False)),
        daemon=True
    ).start()
