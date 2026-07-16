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
import router as msg_router
import subscriptions as subs
from templates_config import get_template, get_checkout_extras
from modules import get_enabled_modules
from onboarding import onboarding
from product_dashboard import dashboard
from admin_panel import admin_panel
from auth import auth
import error_tracker

APP_START_TIME = time.time()

# ─────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ADMIN_SECRET    = os.environ.get("ADMIN_SECRET", "CodedLabs2025")

# In-memory AI pause tracker (per-conversation takeover)
AI_PAUSED = {}
VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN", "jordan_verify_2025")
CATALOG_BASE    = os.environ.get("CATALOG_BASE_URL", "https://bot-test-wddr.onrender.com/shop")
BANK_DETAILS    = os.environ.get("BANK_DETAILS", "Bank: GTBank\nAccount: 0123456789\nName: CodedLabs")
ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")   # Set in Render env vars

app = Flask(__name__)
app.register_blueprint(onboarding)
app.register_blueprint(dashboard)
app.register_blueprint(admin_panel)
app.register_blueprint(auth)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'jordan-codedlabs-2025-change-in-prod')
from datetime import timedelta
app.permanent_session_lifetime = timedelta(days=30)

# ══════════════════════════════════════════════════════
# MESSAGE LOGGING WRAPPER (v5.6)
# ══════════════════════════════════════════════════════

_original_send_text    = wa.send_text
_original_send_buttons = wa.send_buttons
_original_send_list    = wa.send_list

def _logged_send_text(phone, text, client, msg_id=None):
    try:
        result = _original_send_text(phone, text, client)
        if client and isinstance(client, dict) and client.get("id"):
            sender = "merchant" if merch.is_merchant(phone, client) else "jordan"
            db_layer.log_message(str(client["id"]), phone, "outgoing", text, msg_id, sender)
        return result
    except Exception:
        return _original_send_text(phone, text, client)

def _logged_send_buttons(phone, text, buttons, client):
    try:
        result = _original_send_buttons(phone, text, buttons, client)
        if client and isinstance(client, dict) and client.get("id"):
            db_layer.log_message(str(client["id"]), phone, "outgoing", text, None, "jordan")
        return result
    except Exception:
        return _original_send_buttons(phone, text, buttons, client)

def _logged_send_list(phone, body, button_label, sections, client):
    try:
        result = _original_send_list(phone, body, button_label, sections, client)
        if client and isinstance(client, dict) and client.get("id"):
            db_layer.log_message(str(client["id"]), phone, "outgoing", body, None, "jordan")
        return result
    except Exception:
        return _original_send_list(phone, body, button_label, sections, client)

wa.send_text    = _logged_send_text
wa.send_buttons = _logged_send_buttons
wa.send_list    = _logged_send_list

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

    # Log incoming message to inbox (v5.6)
    db_layer.log_message(client_id, phone, "incoming", message, message_id, "customer")

    # Mark as read
    wa.mark_read(message_id, client)


    # ── HUMAN HANDOFF RELAY (v5.6) ──
    # When merchant messages while a customer has human_mode active,
    # relay it to the customer instead of treating as a merchant command.
    if merch.is_merchant(phone, client):
        human_session = db_layer.get_human_mode_session(client_id)
        if human_session:
            msg_upper = message.strip().upper()
            # Merchant ending the handoff
            if msg_upper in ("RESUME", "RESUME BOT", "/RESUME", "/END", "END HANDOFF"):
                cust_phone = human_session["phone"]
                db_layer.end_human_mode(client_id, cust_phone)
                wa.send_text(cust_phone,
                    "✅ The team has ended the handoff. Jordan is back! How can I help?", client)
                wa.send_text(phone, f"✅ Handoff ended. Customer +{cust_phone} is back with Jordan.", client)
                return
            # Known merchant commands — let them through
            known_prefixes = ("TODAY", "ORDERS", "LOW STOCK", "CUSTOMERS", "COMMANDS",
                            "STATS", "SUMMARY", "PRODUCTS", "SETTINGS", "HELP",
                            "CONFIRM ", "DELIVERED ", "CANCEL ", "PAID ", "PROCESSING ")
            is_cmd = msg_upper in ("HI", "HELLO", "START") or any(msg_upper.startswith(p) for p in known_prefixes)
            if not is_cmd and not button_id:
                # Relay to customer
                cust_phone = human_session["phone"]
                wa.send_text(cust_phone, f"💬 *{biz_name} team:* {message}", client)
                wa.send_text(phone, f"✅ Relayed to +{cust_phone}", client)
                return

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

    # ── MODULE ROUTER ───────────────────────────────
    # All message routing handled by router.py.
    # Support runs first (universal), then enabled modules.
    msg_router.route(phone, message, button_id, client, session, customer)
    return


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
    def _safe_process():
        try:
            process_message(phone, message, message_id, matched_client, button_id=button_id)
        except Exception as e:
            error_tracker.track("webhook_drop", str(e), "webhook", critical=True)
            logger.error(f"[Webhook] process_message failed: {e}")

    threading.Thread(target=_safe_process, daemon=True).start()

    return jsonify({"status": "ok"}), 200


# ─────────────────────────────────────────────────────
# MONITORING & HEALTH API
# ─────────────────────────────────────────────────────

@app.route("/api/admin/health")
def admin_health():
    """Full health check with DB + WhatsApp status and error summary."""
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify(error_tracker.full_health_check())


@app.route("/api/admin/errors")
def admin_errors():
    """Get recent tracked errors."""
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    minutes = request.args.get("minutes", 60, type=int)
    limit = request.args.get("limit", 50, type=int)
    return jsonify({
        "summary": error_tracker.get_error_summary(),
        "recent": error_tracker.get_recent_errors(minutes=minutes, limit=limit)
    })


@app.route("/api/admin/metrics")
def admin_metrics():
    """Quick operational metrics."""
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    try:
        clients = db_layer.get_all_clients()
        total_clients = len(clients) if isinstance(clients, list) else 0
        import time as _t
        return jsonify({
            "uptime_seconds": round(_t.time() - APP_START_TIME),
            "clients": total_clients,
            "cached_sessions": len(_session_cache),
            "errors": error_tracker.get_error_summary()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
               "phone_number_id", "wa_token", "whatsapp_number", "merchant_phone",
               "ai_model", "active", "modules_config", "plan",
               "welcome_msg", "bank_details", "biz_hours"}
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

# Dashboard and admin routes are handled by product_dashboard Blueprint.
# /dashboard/<slug>  →  product_dashboard.py
# /admin/<slug>      →  product_dashboard.py (alias)



# ─────────────────────────────────────────────────────
# APPOINTMENT API
# ─────────────────────────────────────────────────────

# Appointment status API is in product_dashboard Blueprint


# ─────────────────────────────────────────────────────
# LEAD API
# ─────────────────────────────────────────────────────

@app.route("/api/<slug>/leads/<ref>/status", methods=["PUT"])
def api_update_lead(slug: str, ref: str):
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404
    body   = request.json or {}
    status = body.get("status", "")
    valid  = {"new", "contacted", "qualified", "converted", "lost"}
    if status not in valid:
        return jsonify({"error": f"Status must be one of: {valid}"}), 400
    ok = db_layer.update_lead_status(ref, str(client["id"]), status)
    return jsonify({"success": ok})


# ─────────────────────────────────────────────────────
# FAQ API
# ─────────────────────────────────────────────────────

@app.route("/api/<slug>/faqs", methods=["GET"])
def api_list_faqs(slug: str):
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404
    faqs = db_layer.get_faqs(str(client["id"]))
    return jsonify({"faqs": faqs})


@app.route("/api/<slug>/faqs", methods=["POST"])
def api_create_faq(slug: str):
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404
    body = request.json or {}
    if not body.get("question") or not body.get("answer"):
        return jsonify({"error": "question and answer required"}), 400
    faq = db_layer.create_faq(
        client_id  = str(client["id"]),
        question   = body["question"],
        answer     = body["answer"],
        sort_order = int(body.get("sort_order", 0))
    )
    return jsonify({"success": True, "faq": faq}), 201


@app.route("/api/<slug>/faqs/<int:faq_id>", methods=["PUT"])
def api_update_faq(slug: str, faq_id: int):
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404
    body    = request.json or {}
    allowed = {"question", "answer", "sort_order", "active"}
    updates = {k: v for k, v in body.items() if k in allowed}
    ok = db_layer.update_faq(faq_id, str(client["id"]), updates)
    return jsonify({"success": ok})


@app.route("/api/<slug>/faqs/<int:faq_id>", methods=["DELETE"])
def api_delete_faq(slug: str, faq_id: int):
    if not _require_admin(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404
    ok = db_layer.delete_faq(faq_id, str(client["id"]))
    return jsonify({"success": ok})


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


# ══════════════════════════════════════════════════════
# MESSAGE INBOX API (v5.6)
# ══════════════════════════════════════════════════════

@app.route("/api/<slug>/conversations")
def api_conversations(slug: str):
    """List all unique customer conversations for this client."""
    secret = request.args.get("secret", "") or request.headers.get("X-Admin-Secret", "")
    if secret != ADMIN_SECRET:
        from flask import session as flask_session
        if not flask_session.get("logged_in"):
            return jsonify({"error": "Unauthorized"}), 403

    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    conversations = db_layer.get_conversation_list(str(client["id"]))
    return jsonify({"conversations": conversations})


@app.route("/api/<slug>/messages")
def api_messages(slug: str):
    """Get message history, optionally filtered by phone."""
    secret = request.args.get("secret", "") or request.headers.get("X-Admin-Secret", "")
    if secret != ADMIN_SECRET:
        from flask import session as flask_session
        if not flask_session.get("logged_in"):
            return jsonify({"error": "Unauthorized"}), 403

    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    phone = request.args.get("phone", "")
    limit = int(request.args.get("limit", 100))

    messages = db_layer.get_messages(
        str(client["id"]),
        phone=phone if phone else None,
        limit=min(limit, 500)
    )
    return jsonify({"messages": messages, "phone": phone or None})


@app.route("/api/<slug>/reply", methods=["POST"])
def api_reply(slug: str):
    """Send a reply as Jordan from the dashboard inbox."""
    secret = request.args.get("secret", "") or request.headers.get("X-Admin-Secret", "")
    if secret != ADMIN_SECRET:
        from flask import session as flask_session
        if not flask_session.get("logged_in"):
            return jsonify({"error": "Unauthorized"}), 403

    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    message = data.get("message", "").strip()

    if not phone or not message:
        return jsonify({"error": "phone and message required"}), 400

    import whatsapp as wa
    success = wa.send_text(phone, message, client)
    return jsonify({"success": success, "phone": phone})






@app.route("/api/<slug>/toggle-ai", methods=["POST"])
def api_toggle_ai(slug: str):
    """Toggle AI auto-responder on/off for a specific phone number."""
    try:
        secret = request.args.get("secret", "") or request.headers.get("X-Admin-Secret", "")
        if secret != ADMIN_SECRET:
            from flask import session as flask_session
            if not flask_session.get("logged_in"):
                return jsonify({"error": "Unauthorized"}), 403

        client = db_layer.get_client_by_slug(slug)
        if not client:
            return jsonify({"error": "Client not found"}), 404

        data = request.get_json(silent=True) or {}
        phone = data.get("phone", "").strip()
        enabled = data.get("enabled", True)

        if not phone:
            return jsonify({"error": "phone required"}), 400

        key = f"{slug}:{phone}"
        if enabled:
            AI_PAUSED.pop(key, None)
        else:
            AI_PAUSED[key] = True

        return jsonify({"success": True, "phone": phone, "ai_enabled": enabled})
    except Exception as e:
        return jsonify({"error": str(e), "type": type(e).__name__}), 500


@app.route("/api/<slug>/ai-status")
def api_ai_status(slug: str):
    """Check if AI is paused for a phone number."""
    secret = request.args.get("secret", "") or request.headers.get("X-Admin-Secret", "")
    if secret != ADMIN_SECRET:
        return jsonify({"error": "Unauthorized"}), 403

    phone = request.args.get("phone", "").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400

    key = f"{slug}:{phone}"
    paused = key in AI_PAUSED
    return jsonify({"phone": phone, "ai_enabled": not paused})



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
