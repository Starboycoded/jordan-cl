# ══════════════════════════════════════════════════════
# JORDAN v5.2 — MERCHANT NOTIFICATIONS + ADMIN COMMANDS
# All merchant context comes from client record in DB.
# Zero global env variables for per-client data.
# ══════════════════════════════════════════════════════

import logging
from datetime import date
import database as db_layer
import whatsapp as wa

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────

def _merchant_phone(client: dict) -> str:
    """
    Always read merchant phone from the client record.
    merchant_phone = owner's personal WA (order notifications, admin commands)
    Falls back to whatsapp_number only if merchant_phone not set.
    Never falls back to a global env var.
    """
    return (client.get("merchant_phone") or "").strip()


def _norm(number: str) -> str:
    """Normalize a phone number: strip +, spaces, dashes."""
    return str(number).replace("+", "").replace(" ", "").replace("-", "").strip()


# ─────────────────────────────────────────────────────
# IDENTIFY IF MESSAGE IS FROM MERCHANT
# ─────────────────────────────────────────────────────

def is_merchant(phone: str, client: dict) -> bool:
    """
    Returns True only if the sender's number matches this
    client's merchant_phone in the database.
    """
    mp = _merchant_phone(client)
    if not mp:
        return False
    return _norm(phone) == _norm(mp)


# ─────────────────────────────────────────────────────
# NOTIFY MERCHANT OF NEW ORDER
# ─────────────────────────────────────────────────────

def notify_new_order(order: dict, items: list, customer: dict, client: dict) -> bool:
    """
    Send a rich order notification to the merchant with action buttons.
    Called immediately after a new order is confirmed.
    """
    merchant_phone = _merchant_phone(client)
    if not merchant_phone:
        logger.warning(
            f"[Notify] No merchant_phone set for client '{client.get('slug')}'. "
            f"Set it in Supabase clients.merchant_phone or via the settings dashboard."
        )
        return False

    currency   = client.get("currency", "NGN")
    order_ref  = order.get("order_ref", "N/A")
    total      = order.get("total", 0)
    address    = order.get("address", "Not provided")
    cust_phone = order.get("phone", "Unknown")
    cust_name  = customer.get("name") or f"+{cust_phone}"
    order_count = int(customer.get("order_count", 1))
    returning   = "🔄 Returning customer" if order_count > 1 else "🆕 New customer"

    items_text = ""
    for item in items:
        items_text += f"  • {item['qty']}x {item['name']} — {currency} {int(item['price'] * item['qty']):,}\n"

    message = (
        f"🔔 *New Order — {client.get('business_name', 'Your Store')}*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📋 Ref: *{order_ref}*\n"
        f"👤 {cust_name} ({returning})\n"
        f"📞 +{cust_phone}\n\n"
        f"🛍️ *Items:*\n{items_text}\n"
        f"💰 *Total: {currency} {int(float(total)):,}*\n"
        f"📍 {address}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Tap a button or reply:\n"
        f"*CONFIRM {order_ref}*  |  *DELIVERED {order_ref}*"
    )

    buttons = [
        {"id": f"mc_confirm_{order_ref}",   "title": "✅ Confirm"},
        {"id": f"mc_packed_{order_ref}",    "title": "📦 Packed"},
        {"id": f"mc_delivered_{order_ref}", "title": "🚀 Delivered"},
    ]

    ok = wa.send_buttons(merchant_phone, message, buttons, client)
    if ok:
        logger.info(f"[Notify] Merchant notified: {order_ref} → {merchant_phone}")
    else:
        logger.warning(f"[Notify] Failed to notify merchant for {order_ref}")
    return ok


def notify_low_stock(client: dict) -> None:
    """Send a low stock alert to the merchant."""
    merchant_phone = _merchant_phone(client)
    if not merchant_phone:
        return

    products   = db_layer.get_products(str(client["id"]))
    low_detail = ""
    for p in products:
        stock = int(p.get("stock", 0))
        if stock == 0:
            low_detail += f"  ❌ *{p['name']}*: Out of stock\n"
        elif stock <= 3:
            low_detail += f"  ⚠️ *{p['name']}*: {stock} left\n"

    if not low_detail:
        return

    msg = (
        f"⚠️ *Stock Alert — {client.get('business_name', 'Your Store')}*\n\n"
        f"{low_detail}\n"
        f"Update stock in your dashboard or reply:\n"
        f"*RESTOCK [product name] [qty]*"
    )
    wa.send_text(merchant_phone, msg, client)


# ─────────────────────────────────────────────────────
# HANDLE MERCHANT COMMANDS
# ─────────────────────────────────────────────────────

def handle_merchant_command(phone: str, message: str, button_id: str, client: dict) -> str | None:
    """
    Process commands sent by the merchant via WhatsApp.
    Returns reply string if handled, None if not a merchant command.
    """
    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")
    msg_upper = message.strip().upper()
    btn       = (button_id or "").lower()

    # ── ORDER STATUS BUTTONS ────────────────────────
    # Format: mc_confirm_ORD-xxx  |  mc_packed_ORD-xxx  |  mc_delivered_ORD-xxx
    if btn.startswith("mc_"):
        parts = btn.split("_", 2)
        if len(parts) == 3:
            action    = parts[1]
            order_ref = parts[2].upper()
            status_map = {
                "confirm":   ("confirmed",  "✅"),
                "packed":    ("confirmed",  "📦"),
                "delivered": ("delivered",  "🚀"),
            }
            status, icon = status_map.get(action, ("confirmed", "✅"))
            ok = db_layer.update_order_status(order_ref, client_id, status)
            if ok:
                _notify_customer_of_status(order_ref, status, client)
                return (
                    f"{icon} *{order_ref}* → *{status.title()}*\n\n"
                    f"Customer has been notified automatically. ✅"
                )
            return f"❌ Could not find order *{order_ref}*. Check the ref and try again."

    # ── TODAY ───────────────────────────────────────
    if msg_upper in ("TODAY", "SUMMARY", "STATS"):
        return _today_summary(client_id, currency, client)

    # ── ORDERS ──────────────────────────────────────
    if msg_upper in ("ORDERS", "PENDING", "PENDING ORDERS"):
        return _pending_orders(client_id, currency)

    # ── LOW STOCK ───────────────────────────────────
    if msg_upper in ("LOW STOCK", "LOWSTOCK", "STOCK", "INVENTORY"):
        return _low_stock_report(client_id)

    # ── CUSTOMERS ───────────────────────────────────
    if msg_upper in ("CUSTOMERS", "CUSTOMER COUNT", "CUSTOMER"):
        analytics = db_layer.get_analytics(client_id)
        return (
            f"👥 *Customers — {client.get('business_name','')}*\n\n"
            f"Total customers: *{analytics['total_customers']}*\n"
            f"Total orders: *{analytics['total_orders']}*\n"
            f"Lifetime revenue: *{currency} {int(analytics['revenue']):,}*"
        )

    # ── REVENUE ─────────────────────────────────────
    if msg_upper in ("REVENUE", "SALES"):
        return _revenue_summary(client_id, currency)

    # ── CONFIRM / PACKED / DELIVERED / CANCEL [ref] ─
    for keyword, status in [
        ("CONFIRM",   "confirmed"),
        ("PACKED",    "confirmed"),
        ("DELIVERED", "delivered"),
        ("CANCEL",    "cancelled"),
    ]:
        if msg_upper.startswith(keyword + " "):
            order_ref = message.strip()[len(keyword):].strip().upper()
            if order_ref:
                ok = db_layer.update_order_status(order_ref, client_id, status)
                if ok:
                    _notify_customer_of_status(order_ref, status, client)
                    icons = {"confirmed": "✅", "delivered": "🚀", "cancelled": "❌"}
                    return (
                        f"{icons.get(status,'✅')} *{order_ref}* → *{status.title()}*\n"
                        f"Customer notified. ✅"
                    )
                return f"❌ Order *{order_ref}* not found. Double-check the ref."

    # ── PAID [ref] — mark payment received ──────────
    if msg_upper.startswith("PAID "):
        order_ref = message.strip()[5:].strip().upper()
        if order_ref:
            ok = db_layer.update_order_status(order_ref, client_id, "paid")
            if ok:
                _notify_customer_of_status(order_ref, "paid", client)
                return f"💰 *{order_ref}* marked as *Paid*. Customer notified. ✅"
            return f"❌ Order *{order_ref}* not found."

    # ── HELP / COMMANDS ─────────────────────────────
    if msg_upper in ("ADMIN", "HELP", "COMMANDS", "ADMIN HELP"):
        return (
            f"⚡ *Jordan Merchant Commands*\n\n"
            f"📊 *TODAY* — today's sales summary\n"
            f"📦 *ORDERS* — pending orders list\n"
            f"⚠️ *LOW STOCK* — items running low\n"
            f"👥 *CUSTOMERS* — customer stats\n"
            f"💰 *REVENUE* — all-time sales\n\n"
            f"*Update order status:*\n"
            f"CONFIRM ORD-20250531-0001\n"
            f"PACKED ORD-20250531-0001\n"
            f"PAID ORD-20250531-0001\n"
            f"DELIVERED ORD-20250531-0001\n"
            f"CANCEL ORD-20250531-0001\n\n"
            f"Or just tap the buttons on order notifications."
        )

    return None  # Not a recognised merchant command


# ─────────────────────────────────────────────────────
# COMMAND RESPONSES
# ─────────────────────────────────────────────────────

def _today_summary(client_id: str, currency: str, client: dict) -> str:
    try:
        all_orders  = db_layer.get_orders(client_id, limit=500)
        today_str   = date.today().isoformat()[:10]
        today       = [o for o in all_orders if str(o.get("created_at", ""))[:10] == today_str]
        revenue     = sum(float(o.get("total", 0)) for o in today if o.get("status") not in ("cancelled",))
        pending     = sum(1 for o in today if o.get("status") == "pending")
        paid        = sum(1 for o in today if o.get("status") == "paid")
        delivered   = sum(1 for o in today if o.get("status") == "delivered")
        unique      = len(set(o.get("phone", "") for o in today))

        analytics   = db_layer.get_analytics(client_id)
        stock_warn  = ""
        if analytics.get("low_stock"):
            names = ", ".join(analytics["low_stock"][:3])
            stock_warn = f"\n\n⚠️ Low stock: {names}"

        return (
            f"📊 *Today — {client.get('business_name','')}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🛒 Total orders: *{len(today)}*\n"
            f"⏳ Pending: *{pending}*\n"
            f"💰 Paid: *{paid}*\n"
            f"🚀 Delivered: *{delivered}*\n"
            f"👥 Unique customers: *{unique}*\n"
            f"💵 Revenue: *{currency} {int(revenue):,}*"
            f"{stock_warn}"
        )
    except Exception as e:
        logger.error(f"[MerchantCmd] _today_summary: {e}")
        return "⚠️ Couldn't fetch today's summary. Try again shortly."


def _pending_orders(client_id: str, currency: str) -> str:
    try:
        orders = db_layer.get_orders(client_id, limit=20, status="pending")
        if not orders:
            return "✅ No pending orders right now!"

        text = f"⏳ *Pending Orders ({len(orders)})*\n\n"
        for o in orders[:10]:
            qty_total = sum(i.get("qty", 1) for i in (o.get("items") or []))
            addr      = str(o.get("address", ""))[:35]
            text += (
                f"📋 *{o['order_ref']}*\n"
                f"   +{o.get('phone','?')} · {currency} {int(float(o.get('total',0))):,} · {qty_total} item(s)\n"
                f"   📍 {addr}{'...' if len(str(o.get('address',''))) > 35 else ''}\n\n"
            )
        if len(orders) > 10:
            text += f"_...and {len(orders) - 10} more in your dashboard._\n\n"
        text += "Reply: *CONFIRM [ref]* · *PAID [ref]* · *DELIVERED [ref]*"
        return text.strip()
    except Exception as e:
        logger.error(f"[MerchantCmd] _pending_orders: {e}")
        return "⚠️ Couldn't fetch orders. Try again shortly."


def _low_stock_report(client_id: str) -> str:
    try:
        products = db_layer.get_products(client_id)
        out  = [p for p in products if int(p.get("stock", 0)) == 0]
        low  = [p for p in products if 0 < int(p.get("stock", 0)) <= 3]

        if not out and not low:
            return "✅ All products are well-stocked. Nothing to worry about!"

        text = "⚠️ *Stock Report*\n\n"
        if out:
            text += "❌ *Out of Stock:*\n"
            for p in out:
                text += f"  • {p['name']}\n"
            text += "\n"
        if low:
            text += "🟡 *Running Low:*\n"
            for p in low:
                text += f"  • {p['name']}: *{p['stock']} remaining*\n"

        text += "\nUpdate stock in your product dashboard."
        return text
    except Exception as e:
        logger.error(f"[MerchantCmd] _low_stock_report: {e}")
        return "⚠️ Couldn't fetch stock info. Try again."


def _revenue_summary(client_id: str, currency: str) -> str:
    try:
        analytics = db_layer.get_analytics(client_id)
        all_orders = db_layer.get_orders(client_id, limit=500)

        this_month = date.today().strftime("%Y-%m")
        month_rev  = sum(
            float(o.get("total", 0)) for o in all_orders
            if str(o.get("created_at", ""))[:7] == this_month
            and o.get("status") not in ("cancelled",)
        )
        return (
            f"💰 *Revenue — {currency}*\n\n"
            f"This month: *{currency} {int(month_rev):,}*\n"
            f"All time: *{currency} {int(analytics['revenue']):,}*\n"
            f"Total orders: *{analytics['total_orders']}*\n"
            f"Delivered: *{analytics['delivered']}*"
        )
    except Exception as e:
        logger.error(f"[MerchantCmd] _revenue_summary: {e}")
        return "⚠️ Couldn't fetch revenue data."


# ─────────────────────────────────────────────────────
# CUSTOMER STATUS NOTIFICATIONS
# ─────────────────────────────────────────────────────

def _notify_customer_of_status(order_ref: str, status: str, client: dict) -> None:
    """Notify the customer when merchant updates their order status."""
    try:
        orders = db_layer.get_orders(str(client["id"]), limit=500)
        order  = next((o for o in orders if o.get("order_ref") == order_ref), None)
        if not order:
            return

        msgs = {
            "confirmed": (
                f"✅ Your order *{order_ref}* has been confirmed!\n\n"
                f"We're preparing your items now. We'll notify you when it ships. 🎉"
            ),
            "paid": (
                f"💰 Payment received for *{order_ref}*. Thank you!\n\n"
                f"Your order is now being processed. 🙏"
            ),
            "delivered": (
                f"🚀 Your order *{order_ref}* is on its way!\n\n"
                f"Expect delivery soon. Thank you for shopping with us! 😊\n\n"
                f"_Any issues? Just reply here._"
            ),
            "cancelled": (
                f"❌ Your order *{order_ref}* has been cancelled.\n\n"
                f"If this is a mistake, please reply here and we'll sort it out."
            ),
        }
        msg = msgs.get(status)
        if msg:
            wa.send_text(order["phone"], msg, client)
    except Exception as e:
        logger.error(f"[Notify] _notify_customer_of_status: {e}")
