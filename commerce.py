# ══════════════════════════════════════════════════════
# JORDAN v5.4 — COMMERCE MODULE
# Handles: products, cart, checkout, orders, tracking
# Used by: fashion, electronics, food, beauty, general
# ══════════════════════════════════════════════════════

import re
import json
import logging
import threading

import database as db_layer
import whatsapp as wa
import ai_engine as ai

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# TRIGGERS
# ─────────────────────────────────────────────────────

MENU_TRIGGERS = frozenset([
    "menu", "products", "shop", "catalogue", "catalog",
    "items", "price list", "btn_shop", "btn_continue",
])
CART_TRIGGERS = frozenset(["cart", "my cart", "view cart", "show cart", "btn_cart"])
CHECKOUT_TRIGGERS = frozenset([
    "checkout", "pay", "order", "confirm order",
    "btn_checkout", "place order", "i'm done", "done",
])
TRACK_TRIGGERS = frozenset([
    "track", "order status", "track order",
    "my orders", "where is my order", "btn_track",
])
GREETING_TRIGGERS = frozenset([
    "hi", "hello", "hey", "start", "hola",
    "good morning", "good afternoon", "good evening",
    "morning", "afternoon", "restart",
])

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

ADD_PATTERN  = re.compile(r"^add\s+(\d+)(?:\s*[x×*]\s*(\d+))?$", re.IGNORECASE)
ADD_BTN_PAT  = re.compile(r"^add_(\d+)_(\d+)$")
PROD_BTN_PAT = re.compile(r"^product_(\d+)$")


def is_trigger(message: str, button_id: str) -> bool:
    msg = message.lower().strip()
    btn = (button_id or "").lower()
    if btn in BUTTON_MAP:
        return True
    if msg in GREETING_TRIGGERS | MENU_TRIGGERS | CART_TRIGGERS | CHECKOUT_TRIGGERS | TRACK_TRIGGERS:
        return True
    if ADD_PATTERN.match(msg) or ADD_BTN_PAT.match(btn) or PROD_BTN_PAT.match(btn):
        return True
    return False


# ─────────────────────────────────────────────────────
# MAIN HANDLER
# ─────────────────────────────────────────────────────

def handle(phone: str, message: str, button_id: str,
           client: dict, session: dict, customer: dict) -> None:

    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")

    # Remap button IDs to commands
    btn = (button_id or "").lower()
    if btn in BUTTON_MAP:
        message = BUTTON_MAP[btn]
    msg = message.lower().strip()

    # ── GREETING ────────────────────────────────────
    if msg in GREETING_TRIGGERS:
        _send_greeting(phone, client, session, customer)
        return

    # ── MENU ────────────────────────────────────────
    if msg in MENU_TRIGGERS:
        _send_menu(phone, client, session)
        return

    # Product list selection
    pm = PROD_BTN_PAT.match(btn or msg)
    if pm:
        _show_product_detail(phone, pm.group(1), client, session)
        return

    # Quick add from product detail button
    ab = ADD_BTN_PAT.match(btn or msg)
    if ab:
        _add_to_cart(phone, ab.group(1), int(ab.group(2)), client, session, customer)
        return

    # ── ADD ITEM ────────────────────────────────────
    am = ADD_PATTERN.match(msg)
    if am:
        pid = am.group(1)
        qty = int(am.group(2) or 1)
        _add_to_cart(phone, pid, qty, client, session, customer)
        return

    # ── REMOVE ITEM ─────────────────────────────────
    rm = re.match(r"^remove\s+(\d+)$", msg)
    if rm:
        _remove_from_cart(phone, rm.group(1), client, session)
        return

    # ── CART ────────────────────────────────────────
    if msg in CART_TRIGGERS:
        _show_cart(phone, client, session)
        return

    # Clear cart buttons
    if msg == "btn_clear":
        session["state"] = "confirm_clear"
        _save(client_id, phone, session)
        wa.send_buttons(phone, "⚠️ Clear your entire cart?",
            [{"id": "btn_yes_clear", "title": "Yes, clear it"},
             {"id": "btn_no",        "title": "No, keep it"}], client)
        return
    if msg in ("btn_yes_clear", "clear cart", "clear"):
        session["cart"]  = {}
        session["state"] = "idle"
        _save(client_id, phone, session)
        wa.send_text(phone, "🗑️ Cart cleared! Type MENU to browse products.", client)
        return

    # ── CHECKOUT ────────────────────────────────────
    if msg in CHECKOUT_TRIGGERS or msg == "btn_checkout":
        _begin_checkout(phone, client, session, customer)
        return

    # ── CONFIRM ORDER ───────────────────────────────
    if msg in ("btn_confirm_order", "confirm", "yes confirm"):
        _confirm_order(phone, client, session, customer)
        return

    # ── CHANGE ADDRESS ──────────────────────────────
    if msg == "btn_change_addr":
        session["state"] = "awaiting_address"
        _save(client_id, phone, session)
        wa.send_text(phone, "📍 Send your updated delivery address:", client)
        return

    # ── CANCEL ORDER ────────────────────────────────
    if msg in ("cancel", "btn_cancel_order"):
        session["state"]           = "idle"
        session["pending_items"]   = []
        session["pending_total"]   = 0
        session["pending_address"] = ""
        _save(client_id, phone, session)
        wa.send_text(phone, "❌ Order cancelled. Type CART to view your saved cart.", client)
        return

    # ── STATE: AWAITING ADDRESS ─────────────────────
    if session.get("state") == "awaiting_address":
        _handle_address_input(phone, message, client, session, customer)
        return

    # ── STATE: CONFIRM ORDER ────────────────────────
    if session.get("state") == "confirm_order":
        if msg in ("yes", "confirm", "ok", "proceed"):
            _confirm_order(phone, client, session, customer)
        else:
            wa.send_text(phone, "Reply YES to confirm or CANCEL to cancel.", client)
        return

    # ── TRACK ───────────────────────────────────────
    if msg in TRACK_TRIGGERS:
        _show_order_history(phone, client_id, phone, client)
        return

    # ── STOREFRONT LINK ─────────────────────────────
    if msg in ("shop", "store", "website", "link", "catalogue link"):
        slug = client.get("slug", "")
        wa.send_text(phone,
            f"🌐 Browse our store:\n{client.get('catalog_url', '')}\n\n"
            "Add to cart and send your order to WhatsApp!", client)
        return

    # ── AI FALLBACK ─────────────────────────────────
    _ai_response(phone, message, client, session, customer)


# ─────────────────────────────────────────────────────
# GREETING
# ─────────────────────────────────────────────────────

def _send_greeting(phone, client, session, customer):
    client_id    = str(client["id"])
    currency     = client.get("currency", "NGN")
    biz_name     = client.get("business_name", "us")
    name         = customer.get("name", "")
    order_count  = int(customer.get("order_count", 0))
    products     = db_layer.get_products(client_id)
    in_stock     = [p for p in products if int(p.get("stock", 0)) > 0]

    session["state"] = "idle"
    session["cart"]  = {}
    _save(client_id, phone, session)

    if order_count > 0:
        greeting = (
            f"Hey {name or 'back'}! 👋 Great to see you again at *{biz_name}*.\n\n"
            f"You've ordered with us {order_count} time(s) before. "
            f"What can I get you today?"
        )
    else:
        greeting = (
            f"Hi{' ' + name if name else ''}! 👋 Welcome to *{biz_name}*.\n\n"
            f"{client.get('greeting', 'How can I help you today?')}"
        )

    if in_stock:
        greeting += f"\n\nWe have *{len(in_stock)} products* available. Type *MENU* to browse."

    wa.send_buttons(phone, greeting,
        [{"id": "btn_shop",  "title": "🛍️ Browse Products"},
         {"id": "btn_cart",  "title": "🛒 My Cart"},
         {"id": "btn_track", "title": "📦 Track Order"}], client)


# ─────────────────────────────────────────────────────
# MENU
# ─────────────────────────────────────────────────────

def _send_menu(phone, client, session):
    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")
    products  = db_layer.get_products(client_id)
    in_stock  = [p for p in products if int(p.get("stock", 0)) > 0]

    if not in_stock:
        wa.send_text(phone, "🏪 Our catalogue is being updated. Check back shortly!", client)
        return

    if len(in_stock) <= 10:
        rows = [{
            "id":          f"product_{p['id']}",
            "title":       p["name"][:24],
            "description": f"{currency} {int(float(p['price'])):,}"
                           + (f" · {p.get('category','')}" if p.get("category") else "")
        } for p in in_stock]
        wa.send_list(phone,
            f"🛍️ *{client.get('business_name', 'Our Store')} — Products*\n\nSelect a product to learn more:",
            "Browse Products",
            [{"title": "Available Products", "rows": rows}], client)
    else:
        text = f"🛍️ *Product Catalogue*\n\n"
        for p in in_stock:
            text += f"• *{p['name']}* — {currency} {int(float(p['price'])):,}\n"
            text += f"  Type: `ADD {p['id']}`\n\n"
        text += f"\n🌐 Full store: {client.get('catalog_url', '')}"
        wa.send_text(phone, text, client)


def _show_product_detail(phone, pid, client, session):
    client_id = str(client["id"])
    products  = db_layer.get_products(client_id)
    currency  = client.get("currency", "NGN")
    prod      = next((p for p in products if str(p["id"]) == str(pid)), None)

    if not prod:
        wa.send_text(phone, "Product not found. Type MENU to see our catalogue.", client)
        return

    stock = int(prod.get("stock", 0))
    text  = (
        f"*{prod['name']}*\n"
        f"💰 {currency} {int(float(prod['price'])):,}\n"
        f"📦 {'✅ In Stock' if stock > 0 else '❌ Out of Stock'}\n"
    )
    if prod.get("description"):
        text += f"\n{prod['description']}"

    if stock > 0:
        wa.send_buttons(phone, text,
            [{"id": f"add_{pid}_1", "title": "Add to Cart"},
             {"id": "btn_shop",     "title": "See All Products"},
             {"id": "btn_cart",     "title": "View Cart"}], client)
    else:
        wa.send_buttons(phone, text,
            [{"id": "btn_shop", "title": "See Other Products"}], client)


# ─────────────────────────────────────────────────────
# CART
# ─────────────────────────────────────────────────────

def _add_to_cart(phone, pid, qty, client, session, customer):
    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")
    products  = db_layer.get_products(client_id)
    prod      = next((p for p in products if str(p["id"]) == str(pid)), None)

    if not prod:
        wa.send_text(phone, f"Product #{pid} not found. Type MENU to browse.", client)
        return
    if int(prod.get("stock", 0)) <= 0:
        wa.send_text(phone, f"😔 *{prod['name']}* is out of stock. Type MENU for alternatives.", client)
        return

    cart      = session.get("cart", {})
    cart[pid] = cart.get(pid, 0) + qty
    session["cart"] = cart
    _save(client_id, phone, session)

    total      = _cart_total(cart, products, currency)
    cart_count = sum(cart.values())

    wa.send_buttons(phone,
        f"✅ *{qty}x {prod['name']}* added!\n\n"
        f"🛒 {cart_count} item(s) · {total}",
        [{"id": "btn_checkout", "title": "✅ Checkout"},
         {"id": "btn_cart",     "title": "🛒 View Cart"},
         {"id": "btn_continue", "title": "➕ Keep Shopping"}], client)


def _remove_from_cart(phone, pid, client, session):
    client_id = str(client["id"])
    cart      = session.get("cart", {})
    if pid in cart:
        del cart[pid]
        session["cart"] = cart
        _save(client_id, phone, session)
        wa.send_text(phone, "🗑️ Item removed. Type CART to view your cart.", client)
    else:
        wa.send_text(phone, "That item isn't in your cart.", client)


def _show_cart(phone, client, session):
    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")
    cart      = session.get("cart", {})
    products  = db_layer.get_products(client_id)

    if not cart:
        wa.send_buttons(phone, "🛒 Your cart is empty!\n\nBrowse our products to get started.",
            [{"id": "btn_shop", "title": "🛍️ Browse Products"}], client)
        return

    pm   = {str(p["id"]): p for p in products}
    text = "🛒 *Your Cart*\n\n"
    total_val = 0
    for pid, qty in cart.items():
        p   = pm.get(str(pid))
        if not p:
            continue
        sub = float(p["price"]) * qty
        total_val += sub
        text += f"• {qty}x {p['name']} — {currency} {int(sub):,}\n"
    text += f"\n💰 *Total: {currency} {int(total_val):,}*"

    wa.send_buttons(phone, text,
        [{"id": "btn_checkout", "title": "✅ Checkout"},
         {"id": "btn_clear",    "title": "🗑️ Clear Cart"},
         {"id": "btn_continue", "title": "➕ Add More"}], client)


def _cart_total(cart, products, currency):
    pm    = {str(p["id"]): p for p in products}
    total = sum(float(pm[pid]["price"]) * qty
                for pid, qty in cart.items() if pid in pm)
    return f"{currency} {int(total):,}"


# ─────────────────────────────────────────────────────
# CHECKOUT
# ─────────────────────────────────────────────────────

def _begin_checkout(phone, client, session, customer):
    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")
    cart      = session.get("cart", {})
    products  = db_layer.get_products(client_id)

    if not cart:
        wa.send_text(phone, "🛒 Your cart is empty! Type MENU to browse first.", client)
        return

    pm         = {str(p["id"]): p for p in products}
    items      = _build_items(cart, pm)
    total      = sum(i["price"] * i["qty"] for i in items)
    cart_lines = "\n".join(f"• {i['qty']}x {i['name']} — {currency} {int(i['price']*i['qty']):,}" for i in items)

    session["pending_items"] = items
    session["pending_total"] = total

    # Returning customer with saved address
    saved_address = customer.get("address", "")
    if saved_address:
        session["state"] = "confirm_order"
        session["pending_address"] = saved_address
        _save(client_id, phone, session)
        wa.send_buttons(phone,
            f"📋 *Order Summary*\n\n{cart_lines}\n\n"
            f"💰 *Total: {currency} {int(total):,}*\n\n"
            f"📍 Deliver to: *{saved_address}*",
            [{"id": "btn_confirm_order", "title": "✅ Confirm Order"},
             {"id": "btn_change_addr",   "title": "📍 Change Address"},
             {"id": "btn_cancel_order",  "title": "❌ Cancel"}], client)
    else:
        session["state"] = "awaiting_address"
        _save(client_id, phone, session)
        wa.send_text(phone,
            f"📋 *Order Summary*\n\n{cart_lines}\n\n"
            f"💰 *Total: {currency} {int(total):,}*\n\n"
            f"📍 Please send your delivery address:", client)


def _handle_address_input(phone, address, client, session, customer):
    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")

    if len(address.strip()) < 10:
        wa.send_text(phone, "Please provide a full address (street, area, city).\nExample: *12 Lagos Street, Ikeja, Lagos*", client)
        return

    session["pending_address"] = address.strip()
    session["state"] = "confirm_order"
    _save(client_id, phone, session)

    items      = session.get("pending_items", [])
    total      = session.get("pending_total", 0)
    cart_lines = "\n".join(f"• {i['qty']}x {i['name']} — {currency} {int(i['price']*i['qty']):,}" for i in items)

    wa.send_buttons(phone,
        f"✅ *Confirm Your Order*\n\n{cart_lines}\n\n"
        f"💰 *Total: {currency} {int(total):,}*\n"
        f"📍 *Deliver to:* {address.strip()}",
        [{"id": "btn_confirm_order", "title": "✅ Confirm Order"},
         {"id": "btn_change_addr",   "title": "📍 Change Address"},
         {"id": "btn_cancel_order",  "title": "❌ Cancel"}], client)


def _confirm_order(phone, client, session, customer):
    from datetime import date as dt
    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")

    items   = session.get("pending_items", [])
    total   = session.get("pending_total", 0)
    address = session.get("pending_address", "Not provided")

    if not items:
        wa.send_text(phone, "Something went wrong. Type CHECKOUT to try again.", client)
        return

    order = db_layer.create_order(
        client_id   = client_id,
        phone       = phone,
        items       = items,
        total       = total,
        address     = address,
        customer_id = customer.get("id")
    )

    # Decrement stock
    for item in items:
        db_layer.decrement_stock(item["product_id"], client_id, item["qty"])

    # Update customer address
    if customer.get("id") and address:
        try:
            db_layer.db().table("customers").update({"address": address}).eq("id", customer["id"]).execute()
        except Exception:
            pass

    # Reset session
    session.update({"cart": {}, "state": "idle", "pending_items": [], "pending_total": 0, "pending_address": ""})
    _save(client_id, phone, session)

    if order:
        import ai_engine as ai
        confirm_msg = ai.generate_order_confirmation({**order, "items": items, "total": total, "address": address}, client)
        wa.send_text(phone, confirm_msg, client)

        from ai_engine import generate_invoice
        import os
        bank_details = os.environ.get("BANK_DETAILS", "Contact us for payment details.")
        wa.send_text(phone, generate_invoice(order["order_ref"], items, total, bank_details, client), client)

        from merchant import notify_new_order
        threading.Thread(target=notify_new_order, args=(order, items, customer, client), daemon=True).start()
    else:
        wa.send_text(phone, "⚠️ Order could not be placed. Please try again or type HUMAN for help.", client)


def _show_order_history(phone, client_id, customer_phone, client):
    orders = db_layer.get_customer_orders(client_id, customer_phone)
    if not orders:
        wa.send_text(phone, "📦 No orders yet! Type MENU to start shopping.", client)
        return

    currency = client.get("currency", "NGN")
    icons    = {"pending": "⏳", "confirmed": "✅", "paid": "💰",
                "processing": "📦", "delivered": "🚀", "cancelled": "❌"}
    text     = "📦 *Your Recent Orders*\n\n"
    for o in orders[:5]:
        icon  = icons.get(o.get("status", "pending"), "📋")
        text += f"{icon} *{o['order_ref']}*\n   {currency} {int(float(o.get('total',0))):,} · {o.get('status','').title()}\n\n"
    wa.send_text(phone, text.strip(), client)


# ─────────────────────────────────────────────────────
# AI FALLBACK
# ─────────────────────────────────────────────────────

def _ai_response(phone, message, client, session, customer):
    client_id = str(client["id"])
    products  = db_layer.get_products(client_id)
    context   = session.get("context", [])
    context.append({"role": "user", "content": message})

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

    if tokens:
        threading.Thread(target=db_layer.log_tokens, args=(client_id, tokens), daemon=True).start()

    wa.send_text(phone, response, client)


# ─────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────

def _build_items(cart: dict, products_map: dict) -> list:
    items = []
    for pid, qty in cart.items():
        p = products_map.get(str(pid))
        if p:
            items.append({
                "product_id": p["id"],
                "name":       p["name"],
                "qty":        qty,
                "price":      float(p["price"])
            })
    return items


def _save(client_id, phone, session):
    threading.Thread(
        target=db_layer.save_session,
        args=(client_id, phone, session.get("state", "idle"),
              session.get("cart", {}), session.get("context", []),
              session.get("human_mode", False)),
        daemon=True
    ).start()
