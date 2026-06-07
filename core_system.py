# ══════════════════════════════════════════════════════
# JORDAN v5.2 — CORE SYSTEM
# CodedLabs | Multi-Tenant WhatsApp Commerce OS
# ══════════════════════════════════════════════════════

import os
import re
import json
import time
import logging
import threading
from flask import Flask, request, jsonify, abort, render_template

import database as db_layer
import whatsapp as wa
import ai_engine as ai
import merchant as merch
import booking_flow
import leadgen_flow
import support_flow
import support_layer
import subscriptions as subs
from templates_config import get_template, get_checkout_extras, get_flow, COMMERCE_TEMPLATES
from onboarding import onboarding
from product_dashboard import dashboard
from admin_panel import admin_panel

# ─────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ADMIN_SECRET    = os.environ.get("ADMIN_SECRET", "CodedLabs2025")
VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN", "jordan_verify_2025")
CATALOG_BASE    = os.environ.get("CATALOG_BASE_URL", "https://bot-test-wddr.onrender.com/shop")
BANK_DETAILS    = os.environ.get("BANK_DETAILS", "Bank: GTBank\nAccount: 0123456789\nName: CodedLabs")
ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")   # Set in Render env vars

app = Flask(__name__)
app.register_blueprint(onboarding)
app.register_blueprint(dashboard)
app.register_blueprint(admin_panel)

# In-memory session cache (backed by Supabase for persistence)
_session_cache: dict = {}   # key: f"{client_id}:{phone}"
_product_cache: dict = {}   # key: client_id  →  {"data": [...], "ts": float}
PRODUCT_CACHE_TTL = 300     # 5 minutes


# ─────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────

def _get_session(client_id: str, phone: str) -> dict:
    key = f"{client_id}:{phone}"
    if key not in _session_cache:
        _session_cache[key] = db_layer.get_session(client_id, phone)
        if not isinstance(_session_cache[key].get("cart"), dict):
            _session_cache[key]["cart"] = {}
        if not isinstance(_session_cache[key].get("context"), list):
            _session_cache[key]["context"] = []
    return _session_cache[key]


def _save_session(client_id: str, phone: str, session: dict):
    key = f"{client_id}:{phone}"
    _session_cache[key] = session
    # Async DB save to avoid blocking
    threading.Thread(
        target=db_layer.save_session,
        args=(client_id, phone, session.get("state", "idle"),
              session.get("cart", {}), session.get("context", []),
              session.get("human_mode", False)),
        daemon=True
    ).start()


def _get_products(client_id: str) -> list:
    now   = time.time()
    entry = _product_cache.get(client_id)
    if entry and (now - entry["ts"]) < PRODUCT_CACHE_TTL:
        return entry["data"]
    products = db_layer.get_products(client_id)
    _product_cache[client_id] = {"data": products, "ts": now}
    return products


def _invalidate_product_cache(client_id: str):
    _product_cache.pop(client_id, None)


def _format_currency(amount: float, currency: str = "NGN") -> str:
    return f"{currency} {int(amount):,}"


def _cart_total(cart: dict, products_map: dict) -> float:
    total = 0.0
    for pid, qty in cart.items():
        p = products_map.get(str(pid)) or products_map.get(int(pid))
        if p:
            total += float(p["price"]) * qty
    return total


def _cart_items(cart: dict, products_map: dict) -> list:
    items = []
    for pid, qty in cart.items():
        p = products_map.get(str(pid)) or products_map.get(int(pid))
        if p:
            items.append({
                "product_id": p["id"],
                "name":       p["name"],
                "qty":        qty,
                "price":      float(p["price"])
            })
    return items


def _products_map(products: list) -> dict:
    return {str(p["id"]): p for p in products}


def _require_admin(req) -> bool:
    secret = req.args.get("secret") or (req.json or {}).get("secret", "") if req.is_json else req.args.get("secret", "")
    return secret == ADMIN_SECRET


# ─────────────────────────────────────────────────────
# MESSAGE PROCESSOR
# ─────────────────────────────────────────────────────

def process_message(phone: str, message: str, message_id: str, client: dict, button_id: str = ""):
    """Core message handling logic for one incoming message."""
    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")
    biz_name  = client.get("business_name", "Jordan")
    msg_lower = message.lower().strip()      # defined here — safe for all checks below

    session   = _get_session(client_id, phone)
    products  = _get_products(client_id)
    prod_map  = _products_map(products)
    customer  = db_layer.get_or_create_customer(client_id, phone)

    # Mark as read
    wa.mark_read(message_id, client)

    # ── MERCHANT COMMANDS (check before customer flow) ──
    if merch.is_merchant(phone, client):
        if button_id and button_id.startswith("apt_"):
            resp = merch.handle_appointment_button(button_id, client)
            if resp:
                wa.send_text(phone, resp, client)
                return
        response = merch.handle_merchant_command(phone, message, button_id, client)
        if response:
            wa.send_text(phone, response, client)
            return
        # Merchant sent something unrecognised — show help
        if message.upper() not in ("HI", "HELLO", "START"):
            wa.send_text(phone,
                f"👋 Merchant mode active.\n\n"
                f"Quick commands: *TODAY* · *ORDERS* · *LOW STOCK* · *CUSTOMERS*\n"
                f"Update orders: *CONFIRM [ref]* · *DELIVERED [ref]*\n\n"
                f"Type *COMMANDS* for full list.", client)
            return

    # ── UNIVERSAL SUPPORT LAYER ─────────────────────
    # Checked before flow dispatch — every template gets
    # FAQ, human handoff, contact info, and issue reporting.
    if support_layer.is_support_trigger(message, button_id) or session.get("state") == "reporting_issue":
        handled = support_layer.handle(phone, message, button_id, client, session, customer)
        if handled:
            return

    # ── FLOW DISPATCHER ─────────────────────────────
    # Route to the correct conversation engine based on template.
    # Commerce stays in this file. All others dispatch out.
    flow = get_flow(client.get("template", "commerce"))

    if flow == "booking":
        booking_flow.handle(phone, message, button_id, client, session, customer)
        return

    if flow == "lead_gen":
        leadgen_flow.handle(phone, message, button_id, client, session, customer)
        return

    if flow == "support":
        support_flow.handle(phone, message, button_id, client, session, customer)
        return

    # flow == "commerce" — continues below
    
    # Button taps send their ID as the message. Map them to
    # the exact same commands the text flow uses so both paths work.
    BUTTON_MAP = {
        "btn_shop":          "menu",
        "btn_cart":          "cart",
        "btn_track":         "track",
        "btn_help":          "help",
        "btn_checkout":      "checkout",
        "btn_continue":      "menu",
        "btn_confirm_order": "btn_confirm_order",
        "btn_change_addr":   "btn_change_addr",
        "btn_cancel_order":  "cancel",
        "btn_clear":         "btn_clear",
        "btn_yes_clear":     "btn_yes_clear",
        "btn_no":            "cart",
    }
    if button_id and button_id in BUTTON_MAP:
        message   = BUTTON_MAP[button_id]
        msg_lower = message.lower().strip()

    # ── HUMAN MODE BLOCK ────────────────────────────
    if session.get("human_mode") and msg_lower != "resume bot":
        wa.send_text(phone,
            "⚠️ You're connected to a human agent. They'll respond shortly.\n"
            "Type *RESUME BOT* to return to the AI assistant.", client)
        return

    # ── RESUME BOT ──────────────────────────────────
    if msg_lower == "resume bot":
        session["human_mode"] = False
        _save_session(client_id, phone, session)
        wa.send_text(phone, "✅ You're back with Jordan! How can I help you?", client)
        return

    # ── HUMAN REQUEST ───────────────────────────────
    if msg_lower in ("human", "agent", "talk to human", "speak to human"):
        session["human_mode"] = True
        _save_session(client_id, phone, session)
        wa.send_text(phone,
            "👤 Connecting you to a human agent...\n"
            "Please hold on. Someone will respond shortly.\n\n"
            "Type *RESUME BOT* to return to the AI assistant.", client)
        return

    # ── CART COMMAND ────────────────────────────────
    if msg_lower in ("cart", "my cart", "view cart", "show cart"):
        cart = session.get("cart", {})
        if not cart:
            wa.send_buttons(phone,
                "🛒 Your cart is empty!\n\nBrowse our products and add items to get started.",
                [{"id": "btn_shop", "title": "View Products"},
                 {"id": "btn_help", "title": "Get Help"}], client)
            return

        cart_text = f"🛒 *Your Cart — {biz_name}*\n\n"
        for pid, qty in cart.items():
            p = prod_map.get(str(pid))
            if p:
                subtotal  = float(p["price"]) * qty
                cart_text += f"• {qty}x {p['name']} — {_format_currency(subtotal, currency)}\n"

        total = _cart_total(cart, prod_map)
        cart_text += f"\n💰 *Total: {_format_currency(total, currency)}*"

        wa.send_buttons(phone, cart_text,
            [{"id": "btn_checkout", "title": "✅ Checkout"},
             {"id": "btn_clear",    "title": "🗑️ Clear Cart"},
             {"id": "btn_continue", "title": "➕ Add More"}], client)
        return

    # ── ADD ITEM: "ADD 42" or "ADD 42 x3" ───────────
    add_match = re.match(r"^add\s+(\d+)(?:\s*[x×*]\s*(\d+))?$", msg_lower)
    if add_match:
        pid  = add_match.group(1)
        qty  = int(add_match.group(2) or 1)
        prod = prod_map.get(pid)
        if not prod:
            wa.send_text(phone, f"❌ Product #{pid} not found. Type *MENU* to see all products.", client)
            return
        if int(prod.get("stock", 0)) <= 0:
            wa.send_text(phone, f"😔 Sorry, *{prod['name']}* is currently out of stock. Check back soon!", client)
            return

        cart      = session.get("cart", {})
        cart[pid] = cart.get(pid, 0) + qty
        session["cart"] = cart
        _save_session(client_id, phone, session)

        total     = _cart_total(cart, prod_map)
        cart_count = sum(cart.values())
        wa.send_buttons(phone,
            f"✅ *{qty}x {prod['name']}* added to cart!\n\n"
            f"🛒 Cart: {cart_count} item(s) — {_format_currency(total, currency)}",
            [{"id": "btn_checkout", "title": "✅ Checkout"},
             {"id": "btn_cart",     "title": "🛒 View Cart"},
             {"id": "btn_continue", "title": "➕ Keep Shopping"}], client)
        return

    # ── REMOVE ITEM: "REMOVE 42" ────────────────────
    rem_match = re.match(r"^remove\s+(\d+)$", msg_lower)
    if rem_match:
        pid  = rem_match.group(1)
        cart = session.get("cart", {})
        if pid in cart:
            del cart[pid]
            session["cart"] = cart
            _save_session(client_id, phone, session)
            wa.send_text(phone, f"🗑️ Item removed from cart.\n\nType *CART* to view your cart.", client)
        else:
            wa.send_text(phone, "That item isn't in your cart.", client)
        return

    # ── CLEAR CART ──────────────────────────────────
    if msg_lower in ("clear cart", "clear", "empty cart") or \
       (session.get("state") == "confirm_clear" and msg_lower in ("yes", "confirm")):
        session["cart"]  = {}
        session["state"] = "idle"
        _save_session(client_id, phone, session)
        wa.send_text(phone, "🗑️ Cart cleared. Start fresh! Type *MENU* to browse products.", client)
        return

    # Button: clear cart
    if message == "btn_clear":
        session["state"] = "confirm_clear"
        _save_session(client_id, phone, session)
        wa.send_buttons(phone, "⚠️ Are you sure you want to clear your cart?",
            [{"id": "btn_yes_clear", "title": "Yes, Clear It"},
             {"id": "btn_no",        "title": "No, Keep It"}], client)
        return

    if message == "btn_yes_clear":
        session["cart"]  = {}
        session["state"] = "idle"
        _save_session(client_id, phone, session)
        wa.send_text(phone, "🗑️ Cart cleared!", client)
        return

    # ── MENU / PRODUCTS ─────────────────────────────
    if msg_lower in ("menu", "products", "shop", "catalogue", "catalog", "items", "btn_shop"):
        if not products:
            wa.send_text(phone, "🏪 Our catalogue is being updated. Check back shortly!", client)
            return

        # Use list message for up to 10 products, plain text for more
        if len(products) <= 10:
            rows = []
            for p in products:
                stock_label = "" if int(p.get("stock", 0)) > 0 else " (Out of Stock)"
                rows.append({
                    "id":          f"product_{p['id']}",
                    "title":       p["name"][:24],
                    "description": f"{_format_currency(float(p['price']), currency)}{stock_label}"
                })
            wa.send_list(phone,
                f"🛍️ *{biz_name} — Our Products*\n\nSelect a product to learn more:",
                "Browse Products",
                [{"title": "Products", "rows": rows}], client)
        else:
            # Plain text for large catalogues
            text = f"🛍️ *{biz_name} — Product Catalogue*\n\n"
            for p in products:
                stock = "✅" if int(p.get("stock", 0)) > 0 else "❌"
                text += f"{stock} *{p['name']}* — {_format_currency(float(p['price']), currency)}\n"
                text += f"   To order: `ADD {p['id']}`\n\n"
            text += f"\n🌐 Full store: {CATALOG_BASE}/{client.get('slug', '')}"
            wa.send_text(phone, text, client)
        return

    # Handle product list selection
    if message.startswith("product_"):
        pid  = message.replace("product_", "")
        prod = prod_map.get(pid)
        if prod:
            stock_label = f"✅ {prod.get('stock', 0)} in stock" if int(prod.get("stock", 0)) > 0 else "❌ Out of Stock"
            text = (
                f"*{prod['name']}*\n"
                f"💰 Price: {_format_currency(float(prod['price']), currency)}\n"
                f"📦 Stock: {stock_label}\n"
            )
            if prod.get("description"):
                text += f"📝 {prod['description']}\n"
            if int(prod.get("stock", 0)) > 0:
                wa.send_buttons(phone, text,
                    [{"id": f"add_{pid}_1",  "title": f"Add 1 to Cart"},
                     {"id": "btn_shop",      "title": "See All Products"},
                     {"id": "btn_cart",      "title": "View Cart"}], client)
            else:
                wa.send_buttons(phone, text,
                    [{"id": "btn_shop",  "title": "See Other Products"},
                     {"id": "btn_help",  "title": "Get Help"}], client)
        return

    # Quick add from product button
    add_btn = re.match(r"^add_(\d+)_(\d+)$", message)
    if add_btn:
        pid, qty   = add_btn.group(1), int(add_btn.group(2))
        fake_msg   = f"ADD {pid}" + (f" x{qty}" if qty > 1 else "")
        process_message(phone, fake_msg, message_id, client)
        return

    # ── CHECKOUT ────────────────────────────────────
    if msg_lower in ("checkout", "pay", "order", "confirm order", "btn_checkout") or \
       message == "btn_checkout":
        cart = session.get("cart", {})
        if not cart:
            wa.send_text(phone, "🛒 Your cart is empty! Browse products first.\n\nType *MENU* to see our catalogue.", client)
            return

        if session.get("state") == "awaiting_address":
            return  # Already in checkout flow

        items = _cart_items(cart, prod_map)
        total = _cart_total(cart, prod_map)
        session["state"]         = "awaiting_address"
        session["pending_items"] = items
        session["pending_total"] = total
        _save_session(client_id, phone, session)

        cart_text = "📋 *Order Summary:*\n\n"
        for item in items:
            cart_text += f"• {item['qty']}x {item['name']} — {_format_currency(item['price'] * item['qty'], currency)}\n"
        cart_text += f"\n💰 *Total: {_format_currency(total, currency)}*\n\n"
        cart_text += "📍 Please send your *delivery address* to proceed:"

        wa.send_text(phone, cart_text, client)
        return

    # ── AWAITING ADDRESS ────────────────────────────
    if session.get("state") == "awaiting_address":
        address = message.strip()
        if len(address) < 10:
            wa.send_text(phone,
                "Please provide a full delivery address (street, area, city).\n"
                "Example: *12 Lagos Street, Ikeja, Lagos*", client)
            return

        session["pending_address"] = address
        session["state"]           = "confirm_order"
        _save_session(client_id, phone, session)

        items = session.get("pending_items", [])
        total = session.get("pending_total", 0)

        summary  = "✅ *Confirm Your Order:*\n\n"
        for item in items:
            summary += f"• {item['qty']}x {item['name']} — {_format_currency(item['price'] * item['qty'], currency)}\n"
        summary += f"\n💰 *Total: {_format_currency(total, currency)}*\n"
        summary += f"📍 *Deliver to:* {address}\n\n"
        summary += "Confirm to place your order:"

        wa.send_buttons(phone, summary,
            [{"id": "btn_confirm_order", "title": "✅ Confirm Order"},
             {"id": "btn_change_addr",   "title": "📍 Change Address"},
             {"id": "btn_cancel_order",  "title": "❌ Cancel"}], client)
        return

    # ── CONFIRM ORDER ───────────────────────────────
    if msg_lower in ("btn_confirm_order", "confirm", "yes confirm") or message == "btn_confirm_order":
        if session.get("state") != "confirm_order":
            wa.send_text(phone, "Type *CHECKOUT* to start an order.", client)
            return

        items   = session.get("pending_items", [])
        total   = session.get("pending_total", 0)
        address = session.get("pending_address", "Not provided")

        order = db_layer.create_order(
            client_id  = client_id,
            phone      = phone,
            items      = items,
            total      = total,
            address    = address,
            customer_id = customer.get("id")
        )

        # Decrement stock
        for item in items:
            db_layer.decrement_stock(item["product_id"], client_id, item["qty"])

        _invalidate_product_cache(client_id)

        # Reset session
        session["cart"]            = {}
        session["state"]           = "idle"
        session["pending_items"]   = []
        session["pending_total"]   = 0
        session["pending_address"] = ""
        _save_session(client_id, phone, session)

        if order:
            # Send confirmation to customer
            confirm_msg = ai.generate_order_confirmation(
                {**order, "items": items, "total": total, "address": address}, client
            )
            wa.send_text(phone, confirm_msg, client)

            # Send invoice with payment details
            invoice_msg = ai.generate_invoice(
                order["order_ref"], items, total, BANK_DETAILS, client
            )
            wa.send_text(phone, invoice_msg, client)

            # 🔔 Notify merchant (async so it doesn't slow down customer response)
            threading.Thread(
                target=merch.notify_new_order,
                args=(order, items, customer, client),
                daemon=True
            ).start()
        else:
            wa.send_text(phone,
                "⚠️ Something went wrong placing your order. Please try again or type *HUMAN* to speak to us.", client)
        return

    # ── CHANGE ADDRESS ──────────────────────────────
    if message == "btn_change_addr":
        session["state"] = "awaiting_address"
        _save_session(client_id, phone, session)
        wa.send_text(phone, "📍 Please send your updated delivery address:", client)
        return

    # ── CANCEL ORDER ────────────────────────────────
    if msg_lower in ("cancel", "btn_cancel_order") or message == "btn_cancel_order":
        session["state"]           = "idle"
        session["pending_items"]   = []
        session["pending_total"]   = 0
        session["pending_address"] = ""
        _save_session(client_id, phone, session)
        wa.send_text(phone, "❌ Order cancelled. Your cart is still saved.\n\nType *CART* to view it.", client)
        return

    # ── TRACK ORDER ─────────────────────────────────
    if msg_lower in ("track", "order status", "track order", "my orders"):
        past_orders = db_layer.get_customer_orders(client_id, phone)
        if not past_orders:
            wa.send_text(phone, "📦 You don't have any orders yet!\n\nType *MENU* to start shopping.", client)
            return

        text = "📦 *Your Recent Orders:*\n\n"
        status_icons = {"pending": "⏳", "confirmed": "✅", "awaiting_payment": "💳", "paid": "💰", "processing": "📦", "delivered": "🚀", "cancelled": "❌"}
        for o in past_orders:
            icon   = status_icons.get(o.get("status", "pending"), "📋")
            text  += f"{icon} *{o['order_ref']}* — {currency} {int(float(o.get('total', 0))):,}\n"
            text  += f"   Status: *{o.get('status', 'pending').title()}*\n\n"
        wa.send_text(phone, text.strip(), client)
        return

    # ── STOREFRONT LINK ─────────────────────────────
    if msg_lower in ("shop", "store", "website", "link", "catalogue link"):
        slug = client.get("slug", "")
        wa.send_text(phone,
            f"🌐 Visit our online store:\n{CATALOG_BASE}/{slug}\n\n"
            f"You can browse, add to cart and send your order directly to WhatsApp!", client)
        return

    # ── GREETING / START ────────────────────────────
    if msg_lower in ("hi", "hello", "hey", "start", "hola", "good morning",
                     "good afternoon", "good evening", "morning", "afternoon"):
        name  = customer.get("name", "")
        greet = f"Hi {name}! 👋" if name else "Hi there! 👋"
        is_returning = int(customer.get("order_count", 0)) > 0

        if is_returning:
            msg = (
                f"{greet} Welcome back to *{biz_name}*! 🎉\n\n"
                f"You've placed *{customer['order_count']} order(s)* with us. Great to see you again!\n\n"
                f"How can I help you today?"
            )
        else:
            msg = (
                f"{greet} Welcome to *{biz_name}*! 😊\n\n"
                f"{client.get('greeting', 'I can help you browse our products and place an order.')}\n\n"
                f"Type *MENU* to see our products, or just tell me what you're looking for!"
            )

        wa.send_buttons(phone, msg,
            [{"id": "btn_shop",  "title": "🛍️ Browse Products"},
             {"id": "btn_cart",  "title": "🛒 My Cart"},
             {"id": "btn_track", "title": "📦 Track Order"}], client)
        return

    # ── HELP ────────────────────────────────────────
    if msg_lower in ("help", "?", "commands", "options"):
        wa.send_text(phone,
            f"*{biz_name} — Quick Commands:*\n\n"
            "🛍️ *MENU* — Browse all products\n"
            "🛒 *CART* — View your cart\n"
            "✅ *CHECKOUT* — Place your order\n"
            "📦 *TRACK* — Check order status\n"
            "🌐 *SHOP* — Online store link\n"
            "👤 *HUMAN* — Speak to a person\n\n"
            "To add an item: *ADD [number]*\n"
            "Example: *ADD 3* or *ADD 3 x2*", client)
        return

    # ── AI FALLBACK ─────────────────────────────────
    # Classify the message first
    classification = ai.classify(message)
    intent         = classification.get("intent", "other")

    # Add to conversation history
    context = session.get("context", [])
    context.append({"role": "user", "content": message})

    # Generate AI response
    response, tokens = ai.chat(
        message  = message,
        history  = context[:-1],   # history without current message
        client   = client,
        products = products,
        customer = customer
    )

    context.append({"role": "assistant", "content": response})
    session["context"] = context
    _save_session(client_id, phone, session)

    # Log token usage async
    if tokens:
        threading.Thread(
            target=db_layer.log_tokens,
            args=(client_id, tokens),
            daemon=True
        ).start()

    wa.send_text(phone, response, client)


# ─────────────────────────────────────────────────────
# WEBHOOK
# ─────────────────────────────────────────────────────

@app.route("/webhook", methods=["GET"])
def webhook_verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge", ""), 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def webhook_receive():
    # Signature verification
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not wa.verify_signature(request.data, sig):
        logger.warning("[Webhook] Invalid signature")
        return "Forbidden", 403

    data = request.get_json(silent=True) or {}
    parsed = wa.parse_webhook(data)

    if not parsed:
        return jsonify({"status": "ok"}), 200

    phone      = parsed["phone"]
    text       = parsed["text"] or ""
    button_id  = parsed["button_id"] or ""
    message    = button_id or text       # button_id takes priority for routing
    message_id = parsed["message_id"]
    phone_id   = parsed["client_phone_id"]

    if not message:
        return jsonify({"status": "ok"}), 200

    # Route to the correct client by phone_number_id
    all_clients = db_layer.get_all_clients()
    matched_client = None
    for c in all_clients:
        if str(c.get("phone_number_id", "")) == str(phone_id):
            matched_client = c
            break

    # Fallback: if only one client or env var match
    if not matched_client and len(all_clients) == 1:
        matched_client = all_clients[0]

    if not matched_client:
        logger.warning(f"[Webhook] No client matched phone_number_id: {phone_id}")
        return jsonify({"status": "ok"}), 200

    # Process in background thread so webhook returns fast
    threading.Thread(
        target=process_message,
        args=(phone, message, message_id, matched_client),
        kwargs={"button_id": button_id},
        daemon=True
    ).start()

    return jsonify({"status": "ok"}), 200


# ─────────────────────────────────────────────────────
# PRODUCT MANAGEMENT API  (for dashboard)
# ─────────────────────────────────────────────────────

@app.route("/api/<slug>/products", methods=["GET"])
def api_list_products(slug: str):
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404
    products = db_layer.get_products(str(client["id"]))
    return jsonify({"products": products})


@app.route("/api/<slug>/products", methods=["POST"])
def api_create_product(slug: str):
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    body = request.json or {}
    required = ["name", "price"]
    if not all(k in body for k in required):
        return jsonify({"error": f"Required fields: {required}"}), 400

    product = db_layer.create_product(
        client_id   = str(client["id"]),
        name        = body["name"],
        price       = float(body["price"]),
        description = body.get("description", ""),
        stock       = int(body.get("stock", 0)),
        image_url   = body.get("image_url", ""),
        category    = body.get("category", "")
    )
    _invalidate_product_cache(str(client["id"]))
    return jsonify({"product": product}), 201


@app.route("/api/<slug>/products/<int:product_id>", methods=["PUT"])
def api_update_product(slug: str, product_id: int):
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    updates = request.json or {}
    allowed = {"name", "price", "description", "stock", "image_url", "category", "active"}
    updates = {k: v for k, v in updates.items() if k in allowed}

    ok = db_layer.update_product(product_id, str(client["id"]), updates)
    _invalidate_product_cache(str(client["id"]))
    return jsonify({"success": ok})


@app.route("/api/<slug>/products/<int:product_id>", methods=["DELETE"])
def api_delete_product(slug: str, product_id: int):
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    ok = db_layer.delete_product(product_id, str(client["id"]))
    _invalidate_product_cache(str(client["id"]))
    return jsonify({"success": ok})


# ─────────────────────────────────────────────────────
# ORDER MANAGEMENT API
# ─────────────────────────────────────────────────────

@app.route("/api/<slug>/orders", methods=["GET"])
def api_list_orders(slug: str):
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    status  = request.args.get("status")
    orders  = db_layer.get_orders(str(client["id"]), limit=200, status=status)
    return jsonify({"orders": orders})


@app.route("/api/<slug>/orders/<order_ref>/status", methods=["PUT"])
def api_update_order(slug: str, order_ref: str):
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    body   = request.json or {}
    status = body.get("status", "")
    valid  = {"pending", "confirmed", "awaiting_payment", "paid", "processing", "delivered", "cancelled"}
    if status not in valid:
        return jsonify({"error": f"Status must be one of: {valid}"}), 400

    ok = db_layer.update_order_status(order_ref, str(client["id"]), status)

    # Notify customer via WhatsApp
    if ok and body.get("notify_customer"):
        orders = db_layer.get_orders(str(client["id"]))
        order  = next((o for o in orders if o["order_ref"] == order_ref), None)
        if order:
            status_msgs = {
                "confirmed":  f"✅ Your order *{order_ref}* has been confirmed! We're preparing it.",
                "delivered":  f"🚀 Your order *{order_ref}* is on its way! Expect delivery soon.",
                "cancelled":  f"❌ Your order *{order_ref}* has been cancelled. Contact us for help."
            }
            msg = status_msgs.get(status)
            if msg:
                wa.send_text(order["phone"], msg, client)

    return jsonify({"success": ok})


# ─────────────────────────────────────────────────────
# CLIENT MANAGEMENT API
# ─────────────────────────────────────────────────────

@app.route("/api/clients", methods=["GET"])
def api_list_clients():
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    clients = db_layer.get_all_clients()
    return jsonify({"clients": clients})


@app.route("/api/clients", methods=["POST"])
def api_create_client():
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    body = request.json or {}
    required = ["slug", "business_name"]
    if not all(k in body for k in required):
        return jsonify({"error": f"Required fields: {required}"}), 400

    client = db_layer.create_client_record(
        slug            = body["slug"],
        business_name   = body["business_name"],
        template        = body.get("template", "general"),
        currency        = body.get("currency", "NGN"),
        phone_number_id = body.get("phone_number_id", "")
    )
    return jsonify({"client": client}), 201


@app.route("/api/clients/<slug>", methods=["PUT"])
def api_update_client(slug: str):
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    updates = request.json or {}
    allowed = {"business_name", "greeting", "template", "currency",
               "phone_number_id", "wa_token", "whatsapp_number", "merchant_phone", "ai_model", "active"}
    updates = {k: v for k, v in updates.items() if k in allowed}

    ok = db_layer.update_client(str(client["id"]), updates)
    return jsonify({"success": ok})


# ─────────────────────────────────────────────────────
# BROADCAST
# ─────────────────────────────────────────────────────

@app.route("/broadcast", methods=["POST"])
def broadcast():
    body = request.json or {}
    if body.get("secret") != ADMIN_SECRET:
        return jsonify({"error": "Unauthorized"}), 403

    slug    = body.get("slug", "")
    message = body.get("message", "").strip()
    if not message:
        return jsonify({"error": "message required"}), 400

    client = db_layer.get_client_by_slug(slug) if slug else db_layer.get_all_clients()[0] if db_layer.get_all_clients() else None
    if not client:
        return jsonify({"error": "Client not found"}), 404

    # Feature gate — broadcast requires Growth plan or above
    if not subs.can(client, "broadcast"):
        return jsonify({"error": subs.upgrade_message(client, "broadcast")}), 403

    customers = db_layer.get_all_customers(str(client["id"]))
    if not customers:
        return jsonify({"sent": 0, "failed": 0, "note": "No customers yet"})

    def run_broadcast():
        sent, failed = wa.broadcast_to_customers(customers, message, client)
        logger.info(f"[Broadcast] {client['business_name']}: {sent} sent, {failed} failed")

    threading.Thread(target=run_broadcast, daemon=True).start()
    return jsonify({
        "status":  "started",
        "message": f"Broadcasting to {len(customers)} customers in background."
    })


# ─────────────────────────────────────────────────────
# STOREFRONT
# ─────────────────────────────────────────────────────

@app.route("/shop/<slug>")
def storefront(slug: str):
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return "Store not found.", 404

    products  = db_layer.get_products(str(client["id"]))
    currency  = client.get("currency", "NGN")
    bot_phone = client.get("whatsapp_number", os.environ.get("BOT_PHONE", ""))

    t_cfg = get_template(client.get("template", "general"))
    pdata = {str(p["id"]): {"name": p["name"], "price": float(p["price"])}
             for p in products if int(p.get("stock", 0)) > 0}

    return render_template("storefront.html",
        client        = client,
        products      = [p for p in products if int(p.get("stock", 0)) > 0],
        currency      = currency,
        bot_phone     = bot_phone,
        products_json = json.dumps(pdata),
        theme         = {
            "primary": t_cfg.get("primary", "#25D366"),
            "bg":      t_cfg.get("bg",      "#07070e"),
            "card_bg": t_cfg.get("card_bg", "#0f1a14"),
            "border":  t_cfg.get("border",  "#1a3020"),
            "tagline": t_cfg.get("tagline", ""),
            "emoji":   t_cfg.get("emoji",   "🛍️"),
        }
    )


# ─────────────────────────────────────────────────────
# ADMIN DASHBOARD
# ─────────────────────────────────────────────────────

@app.route("/admin/<slug>")
@app.route("/admin/<slug>")
def admin_dashboard(slug: str):
    if request.args.get("secret") != ADMIN_SECRET:
        return "Unauthorized. Add ?secret=YOUR_SECRET to the URL.", 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return "Client not found.", 404
    analytics     = db_layer.get_analytics(str(client["id"]))
    orders        = db_layer.get_orders(str(client["id"]), limit=100)
    status_colors = {
        "pending": "#f59e0b", "confirmed": "#3b82f6",
        "awaiting_payment": "#a78bfa", "paid": "#06b6d4",
        "processing": "#f97316", "delivered": "#22c55e", "cancelled": "#ef4444",
    }
    return render_template("admin.html",
        client        = client,
        secret        = request.args.get("secret", ""),
        orders        = orders,
        inventory     = analytics.get("inventory", []),
        currency      = client.get("currency", "NGN"),
        stats         = analytics,
        status_colors = status_colors,
        catalog_url   = f"{CATALOG_BASE}/{client.get('slug','')}",
    )


# ─────────────────────────────────────────────────────
# UTILITY ROUTES
# ─────────────────────────────────────────────────────

@app.route("/refresh")
def refresh():
    if request.args.get("secret") != ADMIN_SECRET:
        return "Unauthorized", 403
    _product_cache.clear()
    _session_cache.clear()
    return "Cache cleared.", 200


@app.route("/ping")
def ping():
    return "pong", 200


@app.route("/")
def health():
    try:
        clients = db_layer.get_all_clients()
        from storage import verify_bucket_exists
        bucket_ok, bucket_msg = verify_bucket_exists()
        return jsonify({
            "status":        "online",
            "version":       "5.3",
            "clients":       len(clients),
            "ai":            "Claude (Anthropic)",
            "storage_bucket": "ok" if bucket_ok else bucket_msg,
            "product":       "Jordan by CodedLabs"
        })
    except Exception as e:
        return jsonify({"status": "degraded", "error": str(e)}), 500


# ─────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
