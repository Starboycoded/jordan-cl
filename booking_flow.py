# ══════════════════════════════════════════════════════
# JORDAN v5.3 — BOOKING FLOW
# For salons, clinics, consultants, tutors, photographers
# Flow: service → date → time → confirm → appointment saved
# ══════════════════════════════════════════════════════

import logging
from datetime import date, datetime, timedelta
import database as db_layer
import whatsapp as wa
import availability as avail

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────
# MAIN HANDLER
# ─────────────────────────────────────────────────────

def handle(phone: str, message: str, button_id: str,
           client: dict, session: dict, customer: dict) -> None:

    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")
    biz_name  = client.get("business_name", "us")
    msg_lower = message.lower().strip()
    btn       = (button_id or "").lower()
    state     = session.get("state", "idle")
    name      = customer.get("name") or session.get("name", "")

    # ── BUTTON MAP ──────────────────────────────────
    BMAP = {
        "bk_services":  "services",
        "bk_mybooks":   "my bookings",
        "bk_help":      "help",
        "bk_cancel":    "cancel booking",
    }
    if btn in BMAP:
        message   = BMAP[btn]
        msg_lower = message.lower()

    # Service selection button: svc_[id]
    if btn.startswith("svc_"):
        service_id = btn.replace("svc_", "")
        _select_service(phone, service_id, client, session, customer)
        return

    # Date selection button: date_[YYYY-MM-DD]
    if btn.startswith("date_"):
        chosen_date = btn.replace("date_", "")
        _select_date(phone, chosen_date, client, session)
        return

    # Time selection button: time_[HH:MM]
    if btn.startswith("time_"):
        chosen_time = btn.replace("time_", "")
        _select_time(phone, chosen_time, client, session, customer)
        return

    # Confirm booking button
    if btn == "bk_confirm" or msg_lower in ("confirm", "yes confirm", "book it"):
        _confirm_booking(phone, client, session, customer)
        return

    # ── RESET ───────────────────────────────────────
    if msg_lower in ("hi", "hello", "hey", "start", "menu", "restart"):
        session["state"]      = "idle"
        session["booking"]    = {}
        _save(client_id, phone, session)
        _send_welcome(phone, name, biz_name, client)
        return

    # ── SERVICES ────────────────────────────────────
    if msg_lower in ("services", "menu", "book", "book appointment", "what do you offer"):
        _show_services(phone, client, session)
        return

    # ── MY BOOKINGS ─────────────────────────────────
    if msg_lower in ("my bookings", "my appointments", "track", "bookings"):
        _show_my_bookings(phone, client_id, phone, client)
        return

    # ── CANCEL BOOKING ──────────────────────────────
    if msg_lower in ("cancel", "cancel booking"):
        session["state"]   = "idle"
        session["booking"] = {}
        _save(client_id, phone, session)
        wa.send_text(phone, "No problem! Your booking has been cancelled. Type *SERVICES* to start again anytime. 😊", client)
        return

    # ── STATE MACHINE ───────────────────────────────
    if state == "awaiting_date":
        # Customer typed a date manually
        _handle_typed_date(phone, message, client, session)
        return

    if state == "awaiting_notes":
        # Optional notes before final confirmation
        session["booking"]["notes"] = message.strip()
        _save(client_id, phone, session)
        _show_booking_summary(phone, client, session, customer)
        return

    # ── FALLBACK ────────────────────────────────────
    wa.send_buttons(phone,
        f"Hi{' ' + name if name else ''}! 👋 I can help you book an appointment at *{biz_name}*.",
        [{"id": "bk_services", "title": "📋 View Services"},
         {"id": "bk_mybooks",  "title": "📅 My Bookings"},
         {"id": "bk_help",     "title": "❓ Help"}], client)


# ─────────────────────────────────────────────────────
# STEPS
# ─────────────────────────────────────────────────────

def _send_welcome(phone: str, name: str, biz_name: str, client: dict):
    greeting_name = f" {name}," if name else "!"
    wa.send_buttons(phone,
        f"Hi{greeting_name} 👋 Welcome to *{biz_name}*.\n\n"
        f"I can help you book an appointment quickly. What would you like to do?",
        [{"id": "bk_services", "title": "📋 Book Appointment"},
         {"id": "bk_mybooks",  "title": "📅 My Bookings"},
         {"id": "bk_help",     "title": "❓ Help"}], client)


def _show_services(phone: str, client: dict, session: dict):
    client_id = str(client["id"])
    services  = db_layer.get_products(client_id)   # Services stored in products table
    currency  = client.get("currency", "NGN")

    if not services:
        wa.send_text(phone,
            "Our services are being updated. Please check back shortly or contact us directly!", client)
        return

    # Use list message if ≤ 10 services
    if len(services) <= 10:
        rows = []
        for s in services:
            duration = s.get("category", "")    # We store duration in category field
            price    = f"{currency} {int(float(s['price'])):,}"
            desc     = f"{price}{' · ' + duration if duration else ''}"
            rows.append({
                "id":          f"svc_{s['id']}",
                "title":       s["name"][:24],
                "description": desc
            })
        wa.send_list(phone,
            "📋 *Our Services*\n\nChoose a service to book:",
            "View Services",
            [{"title": "Available Services", "rows": rows}], client)
    else:
        text = "📋 *Our Services*\n\n"
        for s in services:
            text += f"• *{s['name']}* — {currency} {int(float(s['price'])):,}\n"
            if s.get("description"):
                text += f"  _{s['description']}_\n"
        text += "\nReply with the service name to book."
        wa.send_text(phone, text, client)


def _select_service(phone: str, service_id: str, client: dict,
                    session: dict, customer: dict):
    client_id = str(client["id"])
    services  = db_layer.get_products(client_id)
    service   = next((s for s in services if str(s["id"]) == service_id), None)

    if not service:
        wa.send_text(phone, "Sorry, I couldn't find that service. Type *SERVICES* to see available options.", client)
        return

    session["booking"]                 = {}
    session["booking"]["service_id"]   = service_id
    session["booking"]["service_name"] = service["name"]
    session["booking"]["service_price"] = float(service["price"])
    session["state"]                   = "awaiting_date"
    _save(client_id, phone, session)

    # Show next 7 available days as buttons
    _show_date_picker(phone, service, client)


def _show_date_picker(phone: str, service: dict, client: dict):
    currency = client.get("currency", "NGN")
    today    = date.today()
    buttons  = []

    for i in range(1, 8):
        d     = today + timedelta(days=i)
        label = d.strftime("%a %d %b")          # e.g. "Mon 05 Jun"
        buttons.append({"id": f"date_{d.isoformat()}", "title": label})

    # WhatsApp max 3 buttons — show 3 nearest days + note about others
    wa.send_buttons(phone,
        f"✅ *{service['name']}* — {currency} {int(float(service['price'])):,}\n\n"
        f"📅 Choose a date:\n_(Or type any date e.g. 10 June)_",
        buttons[:3], client)


def _handle_typed_date(phone: str, message: str, client: dict, session: dict):
    """Handle when customer types a date instead of using buttons."""
    from dateutil import parser as dateparser
    try:
        parsed = dateparser.parse(message, dayfirst=True)
        if not parsed:
            raise ValueError()
        chosen = parsed.date().isoformat()
        _select_date(phone, chosen, client, session)
    except:
        wa.send_text(phone,
            "I didn't quite get that date. Please use a format like *10 June* or *2026-06-10*.", client)


def _select_date(phone: str, chosen_date: str, client: dict, session: dict):
    client_id = str(client["id"])
    from templates_config import get_template
    t_cfg     = get_template(client.get("template", "booking"))
    slots     = t_cfg.get("booking_config", {}).get("time_slots",
                ["9:00 AM","10:00 AM","11:00 AM","12:00 PM",
                 "1:00 PM","2:00 PM","3:00 PM","4:00 PM","5:00 PM"])

    session["booking"]["date"] = chosen_date
    session["state"]           = "awaiting_time"
    _save(client_id, phone, session)

    try:
        d_obj      = date.fromisoformat(chosen_date)
        date_label = d_obj.strftime("%A, %d %B %Y")
    except:
        date_label = chosen_date

    # Filter to available slots only
    available = avail.get_available_slots(client_id, chosen_date, slots)

    if not available:
        alts = avail.get_next_available(client_id, slots)
        if alts:
            msg = f"😔 No available slots on *{date_label}*.\n\n✅ *Next available dates:*\n"
            for opt in alts:
                try:
                    lbl = date.fromisoformat(opt["date"]).strftime("%a %d %b")
                except Exception:
                    lbl = opt["date"]
                msg += f"📅 *{lbl}*: {' · '.join(opt['slots'][:3])}\n"
            msg += "\nReply with a date to check availability."
        else:
            msg = "😔 No available slots in the next 7 days. Please contact us directly to arrange a booking."
        session["state"] = "idle"
        _save(client_id, phone, session)
        wa.send_text(phone, msg, client)
        return

    # Show available slots — max 3 buttons, rest as list
    if len(available) <= 3:
        buttons = [{"id": f"time_{s.replace(' ','_')}", "title": s} for s in available]
        wa.send_buttons(phone,
            f"📅 *{date_label}*\n\n{len(available)} slot(s) available. Choose a time:",
            buttons, client)
    else:
        rows = [{"id": f"time_{s.replace(' ','_')}", "title": s, "description": "Available"} for s in available]
        wa.send_list(phone,
            f"📅 *{date_label}* — {len(available)} slots available\n\nChoose your preferred time:",
            "Pick a Time",
            [{"title": "Available Times", "rows": rows}], client)


def _select_time(phone: str, chosen_time: str, client: dict,
                 session: dict, customer: dict):
    client_id  = str(client["id"])
    time_label = chosen_time.replace("_", " ")
    apt_date   = session.get("booking", {}).get("date", "")

    # ── AVAILABILITY CHECK ──────────────────────────
    if apt_date and not avail.is_slot_available(client_id, apt_date, time_label):
        from templates_config import get_template
        t_cfg = get_template(client.get("template", "booking"))
        slots = t_cfg.get("booking_config", {}).get("time_slots",
            ["9:00 AM","10:00 AM","11:00 AM","12:00 PM",
             "1:00 PM","2:00 PM","3:00 PM","4:00 PM","5:00 PM"])
        conflict_msg = avail.build_conflict_message(client_id, apt_date, time_label, slots)
        wa.send_text(phone, conflict_msg, client)
        return  # Stay in awaiting_time state

    session["booking"]["time"] = time_label
    session["state"]           = "awaiting_notes"
    _save(client_id, phone, session)

    service_name = session["booking"].get("service_name", "service")
    wa.send_buttons(phone,
        f"Almost done! ✨\n\n"
        f"📋 Service: *{service_name}*\n"
        f"📅 Date: *{session['booking'].get('date', '')}*\n"
        f"⏰ Time: *{time_label}*\n\n"
        f"Any special notes for us? (or tap Confirm to proceed)",
        [{"id": "bk_confirm", "title": "✅ Confirm Booking"},
         {"id": "bk_cancel",  "title": "❌ Cancel"}], client)


def _show_booking_summary(phone: str, client: dict, session: dict, customer: dict):
    currency     = client.get("currency", "NGN")
    b            = session.get("booking", {})
    service_name = b.get("service_name", "")
    price        = b.get("service_price", 0)
    chosen_date  = b.get("date", "")
    chosen_time  = b.get("time", "")

    wa.send_buttons(phone,
        f"📋 *Booking Summary*\n\n"
        f"💆 Service: *{service_name}*\n"
        f"📅 Date: *{chosen_date}*\n"
        f"⏰ Time: *{chosen_time}*\n"
        f"💰 Price: *{currency} {int(price):,}*\n\n"
        f"Confirm your booking?",
        [{"id": "bk_confirm",  "title": "✅ Confirm"},
         {"id": "bk_services", "title": "🔄 Change Service"},
         {"id": "bk_cancel",   "title": "❌ Cancel"}], client)


def _confirm_booking(phone: str, client: dict, session: dict, customer: dict):
    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")
    b         = session.get("booking", {})

    if not b.get("service_name") or not b.get("date") or not b.get("time"):
        wa.send_text(phone, "Something went wrong. Let's start again — type *SERVICES* to book.", client)
        return

    # Save appointment to DB
    appointment = db_layer.create_appointment(
        client_id    = client_id,
        phone        = phone,
        service_name = b["service_name"],
        service_id   = b.get("service_id"),
        price        = b.get("service_price", 0),
        date         = b["date"],
        time         = b["time"],
        notes        = b.get("notes", ""),
        customer_id  = customer.get("id")
    )

    ref = appointment.get("ref", "APT-0001") if appointment else "APT-0001"

    # Clear session
    session["state"]   = "idle"
    session["booking"] = {}
    _save(client_id, phone, session)

    # Confirm to customer
    wa.send_text(phone,
        f"🎉 *Booking Confirmed!*\n\n"
        f"📋 Ref: *{ref}*\n"
        f"💆 {b['service_name']}\n"
        f"📅 {b['date']} at {b['time']}\n"
        f"💰 {currency} {int(b.get('service_price', 0)):,}\n\n"
        f"We'll send a reminder before your appointment.\n"
        f"To cancel, reply *CANCEL BOOKING*. See you soon! 😊", client)

    # Notify merchant
    from merchant import notify_new_appointment
    import threading
    threading.Thread(
        target=notify_new_appointment,
        args=(appointment or {"ref": ref, **b}, customer, client),
        daemon=True
    ).start()


def _show_my_bookings(phone: str, client_id: str, customer_phone: str, client: dict):
    appointments = db_layer.get_customer_appointments(client_id, customer_phone)
    if not appointments:
        wa.send_buttons(phone,
            "You don't have any appointments yet! Ready to book?",
            [{"id": "bk_services", "title": "📋 Book Now"}], client)
        return

    text = "📅 *Your Appointments*\n\n"
    status_icons = {"pending": "⏳", "confirmed": "✅", "completed": "🎉", "cancelled": "❌"}
    for a in appointments[:5]:
        icon  = status_icons.get(a.get("status", "pending"), "📋")
        text += (
            f"{icon} *{a.get('ref', 'N/A')}*\n"
            f"   {a.get('service_name', '')} · {a.get('date', '')} {a.get('time', '')}\n\n"
        )
    wa.send_text(phone, text.strip(), client)


def _save(client_id, phone, session):
    import threading
    import database as db_layer
    threading.Thread(
        target=db_layer.save_session,
        args=(client_id, phone, session.get("state", "idle"),
              session.get("cart", {}), session.get("context", []),
              session.get("human_mode", False)),
        daemon=True
    ).start()
