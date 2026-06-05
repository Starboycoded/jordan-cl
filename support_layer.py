# ══════════════════════════════════════════════════════
# JORDAN v5.3 — UNIVERSAL SUPPORT LAYER
# Sits above ALL flows. Every business type gets:
#   - FAQ support
#   - Human handoff
#   - Contact business
#   - Issue reporting
# This is checked BEFORE routing to the specific flow.
# ══════════════════════════════════════════════════════

import logging
import database as db_layer
import whatsapp as wa
import ai_engine as ai

logger = logging.getLogger(__name__)

# Triggers that always route to support layer regardless of flow
SUPPORT_TRIGGERS = frozenset([
    "help", "support", "problem", "issue", "complaint",
    "not working", "wrong", "mistake", "error", "refund",
    "contact", "contact us", "phone number", "email",
    "opening hours", "hours", "location", "address", "directions",
    "faq", "faqs", "questions",
])

HUMAN_TRIGGERS = frozenset([
    "human", "agent", "person", "speak to someone",
    "talk to someone", "real person", "customer service",
    "speak to agent", "i need help", "urgent",
])


def is_support_trigger(message: str, button_id: str) -> bool:
    """
    Returns True if this message should be handled by the
    support layer before reaching the flow-specific handler.
    """
    btn = (button_id or "").lower()
    if btn.startswith("sp_"):
        return True

    msg = message.lower().strip()

    # Exact match first
    if msg in SUPPORT_TRIGGERS or msg in HUMAN_TRIGGERS:
        return True

    # Partial match for longer phrases
    for trigger in HUMAN_TRIGGERS:
        if trigger in msg:
            return True

    return False


def handle(phone: str, message: str, button_id: str,
           client: dict, session: dict, customer: dict) -> bool:
    """
    Attempt to handle message as a support request.
    Returns True if handled (caller should return).
    Returns False if not a support message (caller continues to flow).
    """
    client_id = str(client["id"])
    biz_name  = client.get("business_name", "us")
    msg_lower = message.lower().strip()
    btn       = (button_id or "").lower()
    name      = customer.get("name", "")

    # ── BUTTON MAP ──────────────────────────────────
    BMAP = {
        "sp_faq":     "faq",
        "sp_hours":   "opening hours",
        "sp_contact": "contact",
        "sp_human":   "human",
        "sp_report":  "report issue",
    }
    if btn in BMAP:
        msg_lower = BMAP[btn]

    # ── HUMAN HANDOFF ───────────────────────────────
    if msg_lower in HUMAN_TRIGGERS or btn == "sp_human":
        if session.get("human_mode"):
            wa.send_text(phone,
                "You're already connected with our team. "
                "They'll respond shortly.\n"
                "Type *RESUME BOT* to return to Jordan.", client)
            return True

        session["human_mode"] = True
        _save_session(client_id, phone, session)
        wa.send_text(phone,
            f"👤 Connecting you to the *{biz_name}* team now.\n\n"
            f"Please hold on — someone will respond shortly.\n\n"
            f"_Type *RESUME BOT* to return to the AI assistant._", client)

        from merchant import notify_human_handoff
        import threading
        threading.Thread(
            target=notify_human_handoff,
            args=(phone, message, client),
            daemon=True
        ).start()
        return True

    # ── RESUME BOT ──────────────────────────────────
    if msg_lower == "resume bot" and session.get("human_mode"):
        session["human_mode"] = False
        _save_session(client_id, phone, session)
        wa.send_text(phone,
            f"✅ You're back with Jordan! How can I help you?", client)
        return True

    # ── FAQS ────────────────────────────────────────
    if msg_lower in ("faq", "faqs", "questions", "common questions"):
        faqs = db_layer.get_faqs(client_id)
        if not faqs:
            wa.send_text(phone,
                f"We don't have a FAQ list set up yet.\n\n"
                f"Type your question and I'll do my best to help! 😊", client)
            return True

        text = f"❓ *Common Questions — {biz_name}*\n\n"
        for i, faq in enumerate(faqs[:8], 1):
            text += f"*{i}. {faq['question']}*\n{faq['answer']}\n\n"
        text += "_Type your question if you need more help._"
        wa.send_buttons(phone, text,
            [{"id": "sp_human", "title": "👤 Talk to Someone"}], client)
        return True

    # ── OPENING HOURS ────────────────────────────────
    if any(w in msg_lower for w in ("hours", "open", "close", "when are you", "opening")):
        hours = (client.get("business_hours") or "").strip()
        if hours:
            wa.send_text(phone,
                f"🕐 *Opening Hours — {biz_name}*\n\n{hours}", client)
        else:
            wa.send_buttons(phone,
                f"Opening hours haven't been set up yet. "
                f"Contact us directly for more information.",
                [{"id": "sp_human", "title": "👤 Contact Us"},
                 {"id": "sp_contact", "title": "📞 Get Contact Info"}], client)
        return True

    # ── CONTACT INFO ─────────────────────────────────
    if any(w in msg_lower for w in ("contact", "phone number", "email", "address",
                                     "location", "directions", "find you")):
        contact = (client.get("contact_info") or "").strip()
        if contact:
            wa.send_text(phone,
                f"📞 *Contact — {biz_name}*\n\n{contact}", client)
        else:
            wa.send_text(phone,
                f"You're already chatting with us here on WhatsApp! "
                f"Type your question and we'll help. 😊", client)
        return True

    # ── REPORT ISSUE ─────────────────────────────────
    if any(w in msg_lower for w in ("report", "complaint", "complain", "issue", "problem", "wrong")):
        session["state"] = "reporting_issue"
        _save_session(client_id, phone, session)
        wa.send_text(phone,
            f"I'm sorry to hear you're having an issue. 😔\n\n"
            f"Please describe the problem in detail and I'll make sure "
            f"the *{biz_name}* team sees it right away.", client)
        return True

    # ── COLLECTING ISSUE REPORT ──────────────────────
    if session.get("state") == "reporting_issue":
        issue_text = message.strip()
        session["state"] = "idle"
        _save_session(client_id, phone, session)

        # Save as a note on the customer record
        if customer.get("id"):
            try:
                db_layer.db().table("customers").update({
                    "notes": f"Issue reported: {issue_text[:500]}"
                }).eq("id", customer["id"]).execute()
            except Exception:
                pass

        wa.send_text(phone,
            f"✅ Thank you for letting us know.\n\n"
            f"Your issue has been logged and someone from "
            f"the *{biz_name}* team will follow up with you.\n\n"
            f"_Is there anything else I can help you with?_", client)

        # Notify merchant
        from merchant import notify_human_handoff
        import threading
        threading.Thread(
            target=notify_human_handoff,
            args=(phone, f"ISSUE REPORT: {issue_text}", client),
            daemon=True
        ).start()
        return True

    # ── AI FAQ ANSWER ────────────────────────────────
    # If client has FAQ knowledge base enabled, try answering with AI
    from subscriptions import can
    if can(client, "ai_faq_kb"):
        faqs    = db_layer.get_faqs(client_id)
        context = session.get("context", [])
        context.append({"role": "user", "content": message})

        response, tokens = ai.chat_support(
            message  = message,
            history  = context[:-1],
            client   = client,
            faqs     = faqs,
            customer = customer
        )
        context.append({"role": "assistant", "content": response})
        session["context"] = context[-20:]
        _save_session(client_id, phone, session)

        if tokens:
            import threading
            threading.Thread(
                target=db_layer.log_tokens,
                args=(client_id, tokens),
                daemon=True
            ).start()

        wa.send_buttons(phone, response,
            [{"id": "sp_human", "title": "👤 Talk to Someone"},
             {"id": "sp_faq",   "title": "❓ More FAQs"}], client)
        return True

    return False    # Not handled — pass to flow


def _save_session(client_id: str, phone: str, session: dict):
    import threading
    threading.Thread(
        target=db_layer.save_session,
        args=(client_id, phone, session.get("state", "idle"),
              session.get("cart", {}), session.get("context", []),
              session.get("human_mode", False)),
        daemon=True
    ).start()
