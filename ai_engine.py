# ══════════════════════════════════════════════════════
# JORDAN v5.2 — AI ENGINE (Anthropic Claude)
# Default: claude-haiku-4-5  (fast, cheap, good)
# Premium: claude-sonnet-4-6 (upgrade per client)
# ══════════════════════════════════════════════════════

import os
import json
import logging
import requests
from typing import Optional

logger         = logging.getLogger(__name__)
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL  = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VER  = "2023-06-01"

# Model tiers — set per client in DB (client.ai_model)
MODEL_HAIKU    = "claude-haiku-4-5"          # Default — fast, affordable
MODEL_SONNET   = "claude-sonnet-4-6"         # Premium tier for paying clients


def _get_model(client: dict) -> str:
    """Return the right model for this client. Upgrade paying clients to Sonnet."""
    return client.get("ai_model") or MODEL_HAIKU


def _claude(system: str, messages: list, model: str,
            temperature: float = 0.5, max_tokens: int = 512) -> tuple[str, int]:
    """
    Call Anthropic Messages API.
    Returns (response_text, tokens_used).
    """
    if not ANTHROPIC_KEY:
        return "Sorry, AI engine is not configured.", 0

    try:
        r = requests.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key":         ANTHROPIC_KEY,
                "anthropic-version": ANTHROPIC_VER,
                "content-type":      "application/json",
            },
            json={
                "model":       model,
                "max_tokens":  max_tokens,
                "system":      system,
                "messages":    messages,
            },
            timeout=25
        )

        if r.status_code != 200:
            logger.warning(f"[AI] Claude error {r.status_code}: {r.text[:300]}")
            return "I'm having a bit of trouble right now. Please try again in a moment!", 0

        data   = r.json()
        text   = data["content"][0]["text"].strip()
        tokens = data.get("usage", {}).get("input_tokens", 0) + \
                 data.get("usage", {}).get("output_tokens", 0)
        return text, tokens

    except Exception as e:
        logger.error(f"[AI] _claude exception: {e}")
        return "Something went wrong on my end. Please try again!", 0


# ─────────────────────────────────────────────────────
# TRIAGE CLASSIFIER
# ─────────────────────────────────────────────────────

TRIAGE_SYSTEM = """You are a message classifier for a WhatsApp commerce bot.
Classify the user's message and return ONLY valid JSON. No preamble, no markdown, no explanation.

Return this exact structure:
{
  "intent": "order" | "inquiry" | "support" | "greeting" | "cart" | "checkout" | "cancel" | "track" | "human" | "other",
  "product_mention": "product name or null",
  "quantity": integer or null,
  "confidence": 0.0 to 1.0
}

Intent definitions:
- order: wants to buy something
- inquiry: asking about price, availability, specs, description
- support: complaint, issue, help needed
- greeting: hi, hello, hey, start, good morning
- cart: asking about their cart, wants to view cart
- checkout: ready to pay, wants to confirm order
- cancel: wants to cancel order or clear cart
- track: wants to know order status, where is my order
- human: explicitly asking for a human or agent
- other: anything else"""


def classify(message: str) -> dict:
    """Classify a message intent. Uses Haiku always (cheap, fast)."""
    if not message:
        return {"intent": "other", "product_mention": None, "quantity": None, "confidence": 0.5}

    text, _ = _claude(
        system    = TRIAGE_SYSTEM,
        messages  = [{"role": "user", "content": message}],
        model     = MODEL_HAIKU,
        temperature = 0.1,
        max_tokens  = 100
    )
    try:
        clean = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(clean)
    except:
        return {"intent": "other", "product_mention": None, "quantity": None, "confidence": 0.3}


# ─────────────────────────────────────────────────────
# SALES ASSISTANT
# ─────────────────────────────────────────────────────

def build_system_prompt(client: dict, products: list, customer: dict) -> str:
    """Build the system prompt for the sales assistant."""
    from templates_config import get_ai_persona
    biz_name = client.get("business_name", "our store")
    currency = client.get("currency", "NGN")
    template = client.get("template", "general")
    persona  = get_ai_persona(template)

    # Format product catalogue
    catalogue = ""
    for p in products:
        stock_label = "In Stock" if int(p.get("stock", 0)) > 0 else "Out of Stock"
        line = f"  - [{p['id']}] {p['name']}: {currency} {int(p['price']):,} ({stock_label})"
        if p.get("description"):
            line += f" — {p['description']}"
        if p.get("category"):
            line += f" [{p['category']}]"
        catalogue += line + "\n"

    # Customer context
    cust_info = ""
    if customer.get("name"):
        cust_info += f"\nReturning customer: {customer['name']}"
    if int(customer.get("order_count", 0)) > 0:
        cust_info += f"\nPast orders: {customer['order_count']}"
    if float(customer.get("total_spend", 0)) > 0:
        cust_info += f"\nTotal spent: {currency} {int(float(customer['total_spend'])):,}"

    return f"""{persona}

STORE: {biz_name}
CURRENCY: {currency}

PRODUCT CATALOGUE:
{catalogue if catalogue else "  (No products listed yet — tell the customer to check back soon)"}

CUSTOMER INFO:{cust_info if cust_info else " New customer"}

RULES:
1. Be warm, natural and conversational. You're chatting on WhatsApp — not writing an email.
2. Keep responses short: 2–3 sentences max unless the customer asks for detail.
3. When recommending a product, always include its ID in brackets e.g. [42].
4. Never recommend Out of Stock products — suggest alternatives instead.
5. Never invent products, prices, or policies not in the catalogue above.
6. To add to cart: tell customer to type  ADD [id]  e.g.  ADD 42
7. To view cart: CART  |  To checkout: CHECKOUT  |  To track: TRACK
8. If you don't know something, say so honestly and offer to connect them to a person.
9. Never reveal you are an AI unless directly and sincerely asked.
10. Use the customer's name if you know it."""


def chat(message: str, history: list, client: dict,
         products: list, customer: dict) -> tuple[str, int]:
    """
    Generate a sales assistant response.
    history = [{"role": "user"|"assistant", "content": "..."}]
    Returns (response_text, tokens_used).
    """
    system   = build_system_prompt(client, products, customer)
    model    = _get_model(client)

    # Build message list — last 10 turns only
    messages = []
    for turn in history[-10:]:
        role = turn.get("role", "user")
        # Anthropic only accepts "user" and "assistant"
        if role not in ("user", "assistant"):
            continue
        messages.append({"role": role, "content": turn["content"]})

    messages.append({"role": "user", "content": message})

    return _claude(system, messages, model, temperature=0.7, max_tokens=350)


# ─────────────────────────────────────────────────────
# ORDER MESSAGES  (no AI call needed — deterministic)
# ─────────────────────────────────────────────────────

def generate_order_confirmation(order: dict, client: dict) -> str:
    currency   = client.get("currency", "NGN")
    biz_name   = client.get("business_name", "us")
    items_text = ""
    for item in order.get("items", []):
        items_text += f"  • {item['qty']}x {item['name']} — {currency} {int(item['price'] * item['qty']):,}\n"

    return (
        f"✅ *Order Confirmed!*\n\n"
        f"📋 Ref: *{order.get('order_ref', 'N/A')}*\n\n"
        f"{items_text}\n"
        f"💰 *Total: {currency} {int(order.get('total', 0)):,}*\n\n"
        f"📍 Delivering to: {order.get('address', 'Not provided')}\n\n"
        f"We'll send you updates as your order progresses. "
        f"Thank you for shopping with *{biz_name}*! 🙏"
    )


def generate_invoice(order_ref: str, items: list, total: float,
                     bank_details: str, client: dict) -> str:
    currency   = client.get("currency", "NGN")
    biz_name   = client.get("business_name", "us")
    items_text = ""
    for item in items:
        items_text += f"  • {item['qty']}x {item['name']} — {currency} {int(item['price'] * item['qty']):,}\n"

    return (
        f"🧾 *Payment Invoice — {biz_name}*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{items_text}\n"
        f"💰 *Total: {currency} {int(total):,}*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📲 *Pay to:*\n{bank_details}\n\n"
        f"📌 Use *{order_ref}* as your payment reference.\n\n"
        f"Send your payment proof here once done ✅"
    )


# ─────────────────────────────────────────────────────
# SUPPORT CHAT  (FAQ-aware, no product catalogue)
# ─────────────────────────────────────────────────────

def chat_support(message: str, history: list, client: dict,
                 faqs: list, customer: dict) -> tuple[str, int]:
    """AI response for support template — uses FAQ knowledge base."""
    biz_name = client.get("business_name", "us")
    from templates_config import get_ai_persona
    persona  = get_ai_persona(client.get("template", "support"))

    faq_text = ""
    if faqs:
        faq_text = "\nKNOWLEDGE BASE:\n"
        for faq in faqs:
            faq_text += f"Q: {faq['question']}\nA: {faq['answer']}\n\n"

    hours   = client.get("business_hours", "")
    contact = client.get("contact_info", "")
    extra   = ""
    if hours:
        extra += f"\nBusiness Hours:\n{hours}\n"
    if contact:
        extra += f"\nContact Info:\n{contact}\n"

    system = (
        f"{persona}\n\n"
        f"ORGANISATION: {biz_name}\n"
        f"{faq_text}"
        f"{extra}\n"
        f"If you don't know the answer, say so honestly and suggest the customer "
        f"speak to a human agent by typing HUMAN.\n"
        f"Keep replies under 150 words."
    )

    messages = []
    for turn in history[-8:]:
        if turn.get("role") in ("user", "assistant"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": message})

    return _claude(system, messages, MODEL_HAIKU, temperature=0.4, max_tokens=300)
