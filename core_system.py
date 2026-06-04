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
from flask import Flask, request, jsonify, abort

import database as db_layer
import whatsapp as wa
import ai_engine as ai
import merchant as merch
from templates_config import get_template, get_checkout_extras
from onboarding import onboarding
from product_dashboard import dashboard

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

    session   = _get_session(client_id, phone)
    products  = _get_products(client_id)
    prod_map  = _products_map(products)
    customer  = db_layer.get_or_create_customer(client_id, phone)

    # Mark as read
    wa.mark_read(message_id, client)

    # ── MERCHANT COMMANDS (check before customer flow) ──
    if merch.is_merchant(phone, client):
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

    # ── Human handoff mode ──────────────────────────
    if session.get("human_mode"):
        wa.send_text(phone,
            "⚠️ You're connected to a human agent. They'll respond shortly.\n"
            "Type *RESUME BOT* to return to the AI assistant.", client)
        return

    msg_lower = message.lower().strip()

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
    biz_name  = client.get("business_name", "Our Store")

    # Template theming
    t_cfg    = get_template(client.get("template", "general"))
    primary  = t_cfg.get("primary", "#25D366")
    bg       = t_cfg.get("bg",      "#07070e")
    card_bg  = t_cfg.get("card_bg", "#0f1a14")
    border   = t_cfg.get("border",  "#1a3020")
    tagline  = t_cfg.get("tagline", "")
    emoji    = t_cfg.get("emoji",   "🛍️")

    cards = ""
    pdata = {}
    for p in products:
        if int(p.get("stock", 0)) <= 0:
            continue
        pid = str(p["id"])
        pdata[pid] = {"name": p["name"], "price": float(p["price"])}
        img_html = (
            f'<img src="{p["image_url"]}" alt="{p["name"]}" class="pi" loading="lazy">'
            if p.get("image_url") else
            f'<div class="pi pi-placeholder">{emoji}</div>'
        )
        cards += f"""<div class="card" id="c{pid}">
  {img_html}
  <div class="ci">
    <p class="cn">{p['name']}</p>
    <p class="cd">{p.get('description','')}</p>
    <div class="cr">
      <span class="cp">{currency} {int(float(p['price'])):,}</span>
      <button class="btn-add" onclick="addItem({pid})">Add to Cart</button>
    </div>
  </div>
</div>"""

    pdata_json = json.dumps(pdata)

    CSS = f"""
:root{{--green:{primary};--dark:{bg};--card:{card_bg};--muted:#6b7c72;--red:#ff4444;--border:{border}}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Sora',sans-serif;background:var(--dark);color:#e8f5ec;min-height:100vh}}
.hdr{{background:color-mix(in srgb,var(--dark) 60%,#000);border-bottom:1px solid var(--border);padding:16px 20px;position:sticky;top:0;z-index:50}}
.hdr h1{{font-size:18px;font-weight:700;color:#fff}}
.hdr p{{font-size:11px;color:var(--muted);margin-top:2px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:14px;padding:16px}}
.card{{background:var(--card);border-radius:14px;overflow:hidden;transition:transform .2s;border:1px solid var(--border)}}
.card.inc{{border-color:var(--green)}}
.card:hover{{transform:translateY(-2px)}}
.pi{{width:100%;height:160px;object-fit:cover;display:block}}
.pi-placeholder{{width:100%;height:160px;display:flex;align-items:center;justify-content:center;font-size:48px;background:var(--card)}}
.ci{{padding:10px 12px 12px}}
.cn{{font-size:13px;font-weight:600;margin-bottom:4px;line-height:1.3}}
.cd{{font-size:11px;color:var(--muted);margin-bottom:8px;line-height:1.4;min-height:30px}}
.cr{{display:flex;align-items:center;justify-content:space-between;gap:8px}}
.cp{{font-size:13px;font-weight:700;color:var(--green)}}
.btn-add{{background:var(--green);color:#000;border:none;border-radius:8px;padding:7px 12px;font-size:11px;font-weight:700;cursor:pointer;font-family:'Sora',sans-serif;transition:all .15s;white-space:nowrap}}
.btn-add:hover{{opacity:.85}}
.btn-add.flash{{opacity:.7}}
#toast{position:fixed;bottom:90px;left:50%;transform:translateX(-50%) translateY(20px);background:#1a3a24;color:#e8f5ec;padding:10px 18px;border-radius:20px;font-size:13px;opacity:0;transition:all .3s;pointer-events:none;white-space:nowrap;border:1px solid var(--green);z-index:200}
#toast.on{opacity:1;transform:translateX(-50%) translateY(0)}
#cartBtn{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1a3020;color:var(--green);border:2px solid #2d5a3a;border-radius:30px;padding:12px 24px;font-size:14px;font-weight:700;cursor:pointer;font-family:'Sora',sans-serif;transition:all .2s;z-index:100;box-shadow:0 4px 20px rgba(0,0,0,.4)}
#cartBtn.on{background:var(--green);color:#000;border-color:var(--green)}
.cbadge{background:rgba(0,0,0,.2);border-radius:20px;padding:2px 10px;margin-left:6px;font-size:12px}
#ov{position:fixed;inset:0;background:rgba(0,0,0,.7);opacity:0;pointer-events:none;transition:opacity .3s;z-index:150}
#ov.on{opacity:1;pointer-events:all}
#panel{position:fixed;bottom:0;left:0;right:0;background:#0d1f14;border-radius:20px 20px 0 0;transform:translateY(100%);transition:transform .35s cubic-bezier(.4,0,.2,1);z-index:160;max-height:80vh;display:flex;flex-direction:column;border-top:1px solid #1a3020}
#panel.on{transform:translateY(0)}
.ph{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid #1a3020;flex-shrink:0}
.pt{font-size:15px;font-weight:700}
.px{background:none;border:none;color:var(--muted);font-size:20px;cursor:pointer}
.pb{flex:1;overflow-y:auto;padding:10px 20px}
.pe{color:var(--muted);font-size:13px;text-align:center;padding:30px 0}
.row{display:grid;grid-template-columns:1fr auto auto auto;align-items:center;gap:10px;padding:12px 0;border-bottom:1px solid #1a3020}
.rn{font-size:13px;font-weight:600}
.rp{font-size:12px;color:var(--green);font-weight:700;text-align:right;min-width:80px}
.qw{display:flex;align-items:center;gap:5px}
.qb{background:#1a3a24;border:1px solid #2d5a3a;color:var(--green);width:28px;height:28px;border-radius:6px;font-size:16px;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .15s;flex-shrink:0}
.qb:hover{background:#225530}
.qn{font-size:14px;font-weight:700;min-width:20px;text-align:center}
.rd{background:none;border:none;color:#444;cursor:pointer;font-size:16px;padding:4px;line-height:1;transition:color .15s}
.rd:hover{color:var(--red)}
.pf{padding:16px 20px;border-top:1px solid #1a3020;flex-shrink:0}
.tr{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
.tl{font-size:14px;color:var(--muted)}
.tv{font-size:22px;font-weight:700;color:var(--green)}
.bw{width:100%;background:var(--green);color:#000;border:none;font-family:'Sora',sans-serif;font-weight:700;font-size:15px;padding:15px;border-radius:12px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:10px;transition:opacity .15s}
.bw:hover{opacity:.85}
.bc{width:100%;background:none;border:1px solid #2a2a2a;color:var(--muted);font-family:'Sora',sans-serif;font-size:12px;padding:10px;border-radius:8px;cursor:pointer;transition:all .15s}
.bc:hover{border-color:var(--red);color:var(--red)}
.ftr{text-align:center;padding:20px;font-size:11px;color:var(--muted);padding-bottom:80px}
.ftr a{color:var(--green);text-decoration:none}
"""

    JS = f"""
var P={pdata_json};
var PHONE="{bot_phone}";
var cart={{}};
var tt;
function addItem(id){{
  cart[id]=(cart[id]||0)+1;draw();
  show_toast(P[id].name+' added! 🛒');
  var c=document.getElementById('c'+id);
  if(c)c.classList.add('inc');
  var b=c?c.querySelector('.btn-add'):null;
  if(b){{b.textContent='Added ✓';b.classList.add('flash');setTimeout(function(){{b.textContent='Add to Cart';b.classList.remove('flash');}},1400);}}
}}
function inc(id){{cart[id]=(cart[id]||0)+1;draw();}}
function dec(id){{
  cart[id]=(cart[id]||1)-1;
  if(cart[id]<=0){{delete cart[id];var c=document.getElementById('c'+id);if(c)c.classList.remove('inc');}}
  draw();if(!Object.keys(cart).length)close_panel();
}}
function del(id){{
  delete cart[id];
  var c=document.getElementById('c'+id);if(c)c.classList.remove('inc');
  draw();if(!Object.keys(cart).length)close_panel();
}}
function clear_all(){{
  cart={{}};
  document.querySelectorAll('.card').forEach(function(c){{c.classList.remove('inc');}});
  draw();close_panel();
}}
function draw(){{
  var ids=Object.keys(cart);
  var total=0,count=0,html='';
  ids.forEach(function(id){{
    var item=P[id],qty=cart[id],sub=item.price*qty;
    total+=sub;count+=qty;
    html+='<div class="row">'
      +'<span class="rn">'+item.name+'</span>'
      +'<div class="qw">'
      +'<button class="qb" onclick="dec('+id+')">&#8722;</button>'
      +'<span class="qn">'+qty+'</span>'
      +'<button class="qb" onclick="inc('+id+')">&#43;</button>'
      +'</div>'
      +'<span class="rp">{currency} '+sub.toLocaleString()+'</span>'
      +'<button class="rd" onclick="del('+id+')" title="Remove">&#x2715;</button>'
      +'</div>';
  }});
  document.getElementById('pb').innerHTML=html||'<p class="pe">Your cart is empty</p>';
  document.getElementById('tv').textContent='{currency} '+total.toLocaleString();
  document.getElementById('cnt').textContent=count+(count===1?' item':' items');
  var btn=document.getElementById('cartBtn');
  if(count>0)btn.classList.add('on');else btn.classList.remove('on');
}}
function open_panel(){{document.getElementById('panel').classList.add('on');document.getElementById('ov').classList.add('on');}}
function close_panel(){{document.getElementById('panel').classList.remove('on');document.getElementById('ov').classList.remove('on');}}
function show_toast(m){{
  var el=document.getElementById('toast');
  el.textContent=m;el.classList.add('on');
  clearTimeout(tt);tt=setTimeout(function(){{el.classList.remove('on');}},2200);
}}
function send_order(){{
  var ids=Object.keys(cart);
  if(!ids.length){{alert('Your cart is empty!');return;}}
  var total=0,msg='Hi Jordan! I would like to order:\\n\\n';
  ids.forEach(function(id){{
    var item=P[id],qty=cart[id],sub=item.price*qty;
    total+=sub;
    msg+=qty+'x '+item.name+' - {currency} '+sub.toLocaleString()+'\\n';
  }});
  msg+='\\nTotal: {currency} '+total.toLocaleString();
  msg+='\\n\\nPlease confirm my order!';
  window.open('https://wa.me/'+PHONE+'?text='+encodeURIComponent(msg),'_blank');
}}
"""

    return (
        "<!DOCTYPE html><html lang='en'><head>"
        "<meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1.0,maximum-scale=1.0'>"
        f"<title>{biz_name}</title>"
        "<link href='https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700&display=swap' rel='stylesheet'>"
        f"<style>{CSS}</style>"
        "</head><body>"
        f"<header class='hdr'><h1>{emoji} {biz_name}</h1><p>{tagline if tagline else 'Powered by Jordan'}</p></header>"
        "<div id='toast'></div>"
        f"<div class='grid'>{cards if cards else '<p style=\"text-align:center;padding:40px;color:#6b7c72\">No products available yet.</p>'}</div>"
        f"<footer class='ftr'>Powered by Jordan &middot; <a href='https://wa.me/{bot_phone}'>Chat with us</a></footer>"
        "<button id='cartBtn' onclick='open_panel()'>🛒 View Cart <span class='cbadge' id='cnt'>0 items</span></button>"
        "<div id='ov' onclick='close_panel()'></div>"
        "<div id='panel'>"
        "<div class='ph'><span class='pt'>🛒 Your Cart</span><button class='px' onclick='close_panel()'>✕</button></div>"
        "<div class='pb' id='pb'><p class='pe'>Your cart is empty</p></div>"
        "<div class='pf'>"
        "<div class='tr'><span class='tl'>Order Total</span><span class='tv' id='tv'>NGN 0</span></div>"
        "<button class='bw' onclick='send_order()'>Send Order to WhatsApp</button>"
        "<button class='bc' onclick='clear_all()'>Clear cart</button>"
        "</div></div>"
        f"<script>{JS}</script>"
        "</body></html>"
    )


# ─────────────────────────────────────────────────────
# ADMIN DASHBOARD
# ─────────────────────────────────────────────────────

@app.route("/admin/<slug>")
def admin_dashboard(slug: str):
    if request.args.get("secret") != ADMIN_SECRET:
        return "Unauthorized", 403

    client = db_layer.get_client_by_slug(slug)
    if not client:
        return "Client not found", 404

    analytics = db_layer.get_analytics(str(client["id"]))
    orders    = db_layer.get_orders(str(client["id"]), limit=100)
    currency  = client.get("currency", "NGN")
    biz_name  = client.get("business_name", slug)

    status_icons = {"pending": "#f59e0b", "confirmed": "#3b82f6",
                    "awaiting_payment": "#a78bfa", "paid": "#06b6d4",
                    "processing": "#f97316", "delivered": "#22c55e", "cancelled": "#ef4444"}

    order_rows = ""
    for o in orders:
        color = status_icons.get(o.get("status", "pending"), "#888")
        items_summary = ", ".join(
            f"{i['qty']}x {i['name']}" for i in (o.get("items") or [])
        ) if o.get("items") else o.get("items", "—")
        order_rows += f"""<tr>
          <td class="mono">{o.get('order_ref','—')}</td>
          <td>{o.get('phone','—')}</td>
          <td class="sm muted">{items_summary}</td>
          <td class="green">{currency} {int(float(o.get('total',0))):,}</td>
          <td>{o.get('address','—')}</td>
          <td><span class="badge" style="background:{color}22;color:{color}">{o.get('status','pending').title()}</span></td>
          <td class="sm muted">{str(o.get('created_at',''))[:10]}</td>
        </tr>"""

    inv_rows = ""
    for p in analytics["inventory"]:
        stock = int(p.get("stock", 0))
        sc    = "#ef4444" if stock == 0 else "#f59e0b" if stock <= 3 else "#22c55e"
        inv_rows += f"""<tr>
          <td><strong>{p.get('name','')}</strong></td>
          <td class="green">{currency} {int(float(p.get('price',0))):,}</td>
          <td class="sm muted">{p.get('description','')}</td>
          <td><strong style="color:{sc}">{stock}</strong></td>
          <td>
            <button onclick="updateStatus('{slug}','{p.get('id')}','stock')"
              style="background:#1a3020;border:1px solid #2d5a3a;color:#25D366;
              padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px">
              Edit
            </button>
          </td>
        </tr>"""

    low_banner = (
        f'<div class="alert">⚠️ Low/out of stock: {", ".join(analytics["low_stock"])}</div>'
        if analytics["low_stock"] else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{biz_name} — Jordan Admin</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#07070e;--s:#10101a;--b:#1c1c2a;--g:#25D366;--text:#dde;--m:#555}}
body{{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
header{{background:var(--s);border-bottom:1px solid var(--b);padding:15px 28px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10}}
header h1{{font-size:16px;font-weight:700}}
.tag{{font-size:10px;background:rgba(37,211,102,.15);color:var(--g);padding:3px 10px;border-radius:20px;font-weight:600}}
.wrap{{max-width:1200px;margin:0 auto;padding:22px 24px 60px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:24px}}
.stat{{background:var(--s);border:1px solid var(--b);border-radius:14px;padding:18px}}
.stat-n{{font-size:24px;font-weight:700;margin-bottom:2px}}
.stat-l{{font-size:10px;color:var(--m);text-transform:uppercase;letter-spacing:.8px}}
.alert{{background:#231400;border:1px solid #f59e0b;border-radius:10px;padding:11px 16px;font-size:13px;color:#f59e0b;margin-bottom:20px}}
.card{{background:var(--s);border:1px solid var(--b);border-radius:14px;overflow:hidden;margin-bottom:22px}}
.card-head{{padding:12px 18px;border-bottom:1px solid var(--b);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--m);display:flex;justify-content:space-between;align-items:center}}
.tbl-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{padding:10px 14px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.7px;color:var(--m);font-weight:600;border-bottom:1px solid var(--b)}}
td{{padding:10px 14px;border-top:1px solid var(--b);vertical-align:middle}}
tr:hover td{{background:rgba(255,255,255,.015)}}
.mono{{font-family:monospace;font-size:11px}}.muted{{color:var(--m)}}.sm{{font-size:11px}}
.green{{color:var(--g);font-weight:600}}
.badge{{padding:3px 10px;border-radius:20px;font-size:10px;font-weight:700}}
.bcast{{padding:18px}}.bcast p{{font-size:13px;color:var(--m);margin-bottom:10px}}
textarea{{width:100%;background:#0b0b15;border:1px solid var(--b);border-radius:10px;color:var(--text);padding:12px;font-family:inherit;font-size:13px;resize:vertical;outline:none;transition:border-color .2s;min-height:90px}}
textarea:focus{{border-color:var(--g)}}
.btn{{background:var(--g);color:#000;border:none;padding:10px 22px;border-radius:8px;font-weight:700;font-size:13px;cursor:pointer;transition:opacity .15s}}
.btn:hover{{opacity:.85}}
#result{{margin-top:10px;font-size:12px;color:var(--g);min-height:16px}}
select{{background:#0b0b15;border:1px solid var(--b);color:var(--text);padding:4px 8px;border-radius:6px;font-size:11px}}
</style></head><body>
<header>
  <h1>⚡ {biz_name} — Jordan Admin</h1>
  <span class="tag">Jordan v5</span>
</header>
<div class="wrap">
  <div class="stats">
    <div class="stat"><div class="stat-n" style="color:var(--g)">{analytics['total_orders']}</div><div class="stat-l">Total Orders</div></div>
    <div class="stat"><div class="stat-n" style="color:#f59e0b">{analytics['pending']}</div><div class="stat-l">Pending</div></div>
    <div class="stat"><div class="stat-n" style="color:#22c55e">{analytics['delivered']}</div><div class="stat-l">Delivered</div></div>
    <div class="stat"><div class="stat-n" style="color:#3b82f6">{analytics['total_customers']}</div><div class="stat-l">Customers</div></div>
    <div class="stat"><div class="stat-n" style="color:#a78bfa">{currency} {int(analytics['revenue']):,}</div><div class="stat-l">Revenue</div></div>
  </div>
  {low_banner}
  <div class="card">
    <div class="card-head">
      <span>📦 Orders (last 100)</span>
      <select id="statusFilter" onchange="filterOrders()">
        <option value="">All</option>
        <option value="pending">Pending</option>
        <option value="confirmed">Confirmed</option>
        <option value="delivered">Delivered</option>
        <option value="cancelled">Cancelled</option>
      </select>
    </div>
    <div class="tbl-wrap"><table id="ordersTable">
      <thead><tr><th>Ref</th><th>Phone</th><th>Items</th><th>Total</th><th>Address</th><th>Status</th><th>Date</th></tr></thead>
      <tbody>{order_rows}</tbody>
    </table></div>
  </div>
  <div class="card">
    <div class="card-head"><span>🗃️ Inventory</span></div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Product</th><th>Price</th><th>Description</th><th>Stock</th><th>Actions</th></tr></thead>
      <tbody>{inv_rows}</tbody>
    </table></div>
  </div>
  <div class="card">
    <div class="card-head"><span>📣 Broadcast</span></div>
    <div class="bcast">
      <p>Send a message to all {analytics['total_customers']} customers. Runs in background, rate-limited for safety.</p>
      <textarea id="msg" placeholder="Flash sale today! 🔥 Visit our store: {CATALOG_BASE}/{slug}"></textarea>
      <br><button class="btn" onclick="sendBroadcast()">Send to All Customers</button>
      <div id="result"></div>
    </div>
  </div>
</div>
<script>
const SLUG='{slug}';const SECRET='{ADMIN_SECRET}';
async function sendBroadcast(){{
  const msg=document.getElementById('msg').value.trim();
  const r=document.getElementById('result');
  if(!msg){{r.textContent='Write a message first.';return;}}
  r.textContent='Starting broadcast...';
  try{{
    const res=await fetch('/broadcast',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{secret:SECRET,slug:SLUG,message:msg}})}});
    const d=await res.json();
    r.textContent=d.message||'Broadcast started!';
  }}catch(e){{r.textContent='Broadcast failed.';}}
}}
async function updateStatus(slug,ref,field){{
  const newStatus=prompt('New status: pending / confirmed / delivered / cancelled');
  if(!newStatus)return;
  const res=await fetch(`/api/${{slug}}/orders/${{ref}}/status`,{{
    method:'PUT',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{secret:SECRET,status:newStatus,notify_customer:true}})
  }});
  const d=await res.json();
  if(d.success){{alert('Updated! Refreshing...');location.reload();}}
  else alert('Update failed.');
}}
</script>
</body></html>"""


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
        return jsonify({
            "status":   "online",
            "version":  "5.2",
            "clients":  len(clients),
            "ai":       "Claude (Anthropic)",
            "product":  "Jordan by CodedLabs"
        })
    except Exception as e:
        return jsonify({"status": "degraded", "error": str(e)}), 500


# ─────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
