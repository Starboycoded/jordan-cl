# ══════════════════════════════════════════════════════
# JORDAN v5.4 — BOOKING MODULE
# Handles: services, availability, appointments, status
# Used by: salon, clinic, booking, consultant templates
# ══════════════════════════════════════════════════════

import logging
import threading
from datetime import date, timedelta

import database as db_layer
import whatsapp as wa
import availability as avail

logger = logging.getLogger(__name__)

DEFAULT_SLOTS = [
    "9:00 AM","10:00 AM","11:00 AM","12:00 PM",
    "1:00 PM","2:00 PM","3:00 PM","4:00 PM","5:00 PM"
]

BUTTON_MAP = {
    "bk_services": "services",
    "bk_mybooks":  "my bookings",
    "bk_cancel":   "cancel booking",
    "bk_confirm":  "confirm booking",
}


def is_trigger(message: str, button_id: str) -> bool:
    btn = (button_id or "").lower()
    msg = message.lower().strip()
    if btn in BUTTON_MAP or btn.startswith(("svc_", "date_", "time_", "bk_", "apt_")):
        return True
    if msg in ("services", "book", "book appointment", "my bookings", "appointments",
               "hi", "hello", "hey", "start", "menu"):
        return True
    return False


def handle(phone: str, message: str, button_id: str,
           client: dict, session: dict, customer: dict) -> None:

    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")
    btn       = (button_id or "").lower()
    msg       = message.lower().strip()
    name      = customer.get("name", "")

    # Remap buttons
    if btn in BUTTON_MAP:
        msg = BUTTON_MAP[btn]

    # Service selection
    if btn.startswith("svc_"):
        _select_service(phone, btn.replace("svc_", ""), client, session, customer)
        return

    # Date selection
    if btn.startswith("date_"):
        _select_date(phone, btn.replace("date_", ""), client, session)
        return

    # Time selection
    if btn.startswith("time_"):
        _select_time(phone, btn.replace("time_", "").replace("_", " "), client, session, customer)
        return

    # Confirm booking
    if msg in ("confirm booking", "confirm", "yes confirm", "book it") or btn == "bk_confirm":
        _confirm_booking(phone, client, session, customer)
        return

    # Reset / greeting
    if msg in ("hi", "hello", "hey", "start", "menu", "restart"):
        session["state"]   = "idle"
        session["booking"] = {}
        _save(client_id, phone, session)
        _send_welcome(phone, name, client)
        return

    # Services list
    if msg in ("services", "book", "book appointment", "what do you offer", "menu"):
        _show_services(phone, client)
        return

    # My bookings
    if msg in ("my bookings", "my appointments", "bookings", "appointments"):
        _show_my_bookings(phone, client_id, phone, client)
        return

    # Cancel
    if msg in ("cancel", "cancel booking"):
        session["state"]   = "idle"
        session["booking"] = {}
        _save(client_id, phone, session)
        wa.send_text(phone, "No problem! Type *SERVICES* to browse and book anytime. 😊", client)
        return

    # Awaiting typed date
    if session.get("state") == "awaiting_date":
        _handle_typed_date(phone, message, client, session)
        return

    # Awaiting notes
    if session.get("state") == "awaiting_notes":
        session["booking"]["notes"] = message.strip()
        _save(client_id, phone, session)
        _show_booking_summary(phone, client, session)
        return

    # Fallback
    _send_welcome(phone, name, client)


def _send_welcome(phone, name, client):
    biz_name = client.get("business_name", "us")
    greeting = f"Hi{', ' + name if name else ''}! 👋"
    wa.send_buttons(phone,
        f"{greeting} Welcome to *{biz_name}*.\n\n"
        "I can help you book an appointment quickly.",
        [{"id": "bk_services", "title": "📋 Book Appointment"},
         {"id": "bk_mybooks",  "title": "📅 My Bookings"}], client)


def _show_services(phone, client):
    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")
    services  = db_layer.get_products(client_id)

    if not services:
        wa.send_text(phone, "Our services are being updated. Please check back shortly!", client)
        return

    if len(services) <= 10:
        rows = [{
            "id":          f"svc_{s['id']}",
            "title":       s["name"][:24],
            "description": f"{currency} {int(float(s['price'])):,}"
                           + (f" · {s.get('category','')}" if s.get("category") else "")
        } for s in services]
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
        wa.send_text(phone, text, client)


def _select_service(phone, service_id, client, session, customer):
    client_id = str(client["id"])
    services  = db_layer.get_products(client_id)
    service   = next((s for s in services if str(s["id"]) == service_id), None)

    if not service:
        wa.send_text(phone, "Service not found. Type *SERVICES* to see options.", client)
        return

    session["booking"] = {
        "service_id":    service_id,
        "service_name":  service["name"],
        "service_price": float(service["price"]),
    }
    session["state"] = "awaiting_date"
    _save(client_id, phone, session)
    _show_date_picker(phone, service, client)


def _show_date_picker(phone, service, client):
    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")
    today     = date.today()
    slots     = _get_slots(client)

    # Find first 3 days with availability
    buttons = []
    for i in range(1, 14):
        if len(buttons) >= 3:
            break
        d     = today + timedelta(days=i)
        avail_slots = avail.get_available_slots(client_id, d.isoformat(), slots)
        if avail_slots:
            buttons.append({"id": f"date_{d.isoformat()}", "title": d.strftime("%a %d %b")})

    if not buttons:
        wa.send_text(phone,
            "😔 No available slots in the next 2 weeks. Please contact us directly.", client)
        return

    wa.send_buttons(phone,
        f"✅ *{service['name']}* — {currency} {int(float(service['price'])):,}\n\n"
        "📅 Choose a date:\n_(Or type any date e.g. *10 June*)_",
        buttons, client)


def _handle_typed_date(phone, message, client, session):
    try:
        from dateutil import parser as dp
        parsed = dp.parse(message, dayfirst=True)
        _select_date(phone, parsed.date().isoformat(), client, session)
    except Exception:
        wa.send_text(phone,
            "I didn't catch that date. Try *10 June* or *2026-06-10*.", client)


def _select_date(phone, chosen_date, client, session):
    client_id = str(client["id"])
    slots     = _get_slots(client)
    available = avail.get_available_slots(client_id, chosen_date, slots)

    try:
        label = date.fromisoformat(chosen_date).strftime("%A, %d %B %Y")
    except Exception:
        label = chosen_date

    session["booking"]["date"] = chosen_date
    session["state"]           = "awaiting_time"
    _save(client_id, phone, session)

    if not available:
        alts = avail.get_next_available(client_id, slots,
            start_date=date.fromisoformat(chosen_date) if chosen_date else None)
        if alts:
            msg = f"😔 No available slots on *{label}*.\n\n✅ *Next available:*\n"
            for opt in alts:
                try:
                    lbl = date.fromisoformat(opt["date"]).strftime("%a %d %b")
                except Exception:
                    lbl = opt["date"]
                msg += f"📅 *{lbl}*: {' · '.join(opt['slots'][:3])}\n"
            msg += "\nReply with a date to continue."
        else:
            msg = "😔 No available slots nearby. Please contact us directly."
        session["state"] = "awaiting_date"
        _save(client_id, phone, session)
        wa.send_text(phone, msg, client)
        return

    if len(available) <= 3:
        buttons = [{"id": f"time_{s.replace(' ','_')}", "title": s} for s in available]
        wa.send_buttons(phone,
            f"📅 *{label}* — {len(available)} slot(s) available\n\nChoose a time:",
            buttons, client)
    else:
        rows = [{"id": f"time_{s.replace(' ','_')}", "title": s, "description": "Available"} for s in available]
        wa.send_list(phone,
            f"📅 *{label}* — {len(available)} available\n\nChoose your preferred time:",
            "Pick a Time",
            [{"title": "Available Times", "rows": rows}], client)


def _select_time(phone, time_label, client, session, customer):
    client_id  = str(client["id"])
    apt_date   = session.get("booking", {}).get("date", "")
    slots      = _get_slots(client)

    # Double-check availability
    if apt_date and not avail.is_slot_available(client_id, apt_date, time_label):
        conflict_msg = avail.build_conflict_message(client_id, apt_date, time_label, slots)
        wa.send_text(phone, conflict_msg, client)
        return

    session["booking"]["time"] = time_label
    session["state"]           = "awaiting_notes"
    _save(client_id, phone, session)

    b = session["booking"]
    wa.send_buttons(phone,
        f"Almost there! ✨\n\n"
        f"📋 *{b['service_name']}*\n"
        f"📅 {b['date']} at {time_label}\n\n"
        f"Any notes for us? (or tap Confirm)",
        [{"id": "bk_confirm", "title": "✅ Confirm Booking"},
         {"id": "bk_cancel",  "title": "❌ Cancel"}], client)


def _show_booking_summary(phone, client, session):
    currency = client.get("currency", "NGN")
    b        = session.get("booking", {})
    wa.send_buttons(phone,
        f"📋 *Booking Summary*\n\n"
        f"💆 *{b.get('service_name','')}*\n"
        f"📅 {b.get('date','')} at {b.get('time','')}\n"
        f"💰 {currency} {int(b.get('service_price',0)):,}\n"
        f"📝 {b.get('notes','None')}\n\n"
        f"Confirm your booking?",
        [{"id": "bk_confirm",  "title": "✅ Confirm"},
         {"id": "bk_services", "title": "🔄 Change"},
         {"id": "bk_cancel",   "title": "❌ Cancel"}], client)


def _confirm_booking(phone, client, session, customer):
    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")
    b         = session.get("booking", {})

    if not b.get("service_name") or not b.get("date") or not b.get("time"):
        wa.send_text(phone, "Something went wrong. Type *SERVICES* to start again.", client)
        return

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

    session["state"]   = "idle"
    session["booking"] = {}
    _save(client_id, phone, session)

    wa.send_text(phone,
        f"🎉 *Booking Confirmed!*\n\n"
        f"📋 Ref: *{ref}*\n"
        f"💆 {b['service_name']}\n"
        f"📅 {b['date']} at {b['time']}\n"
        f"💰 {currency} {int(b.get('service_price',0)):,}\n\n"
        f"We'll send a reminder before your appointment.\n"
        f"To cancel, reply *CANCEL BOOKING*. See you soon! 😊", client)

    from merchant import notify_new_appointment
    threading.Thread(target=notify_new_appointment,
        args=(appointment or {"ref": ref, **b}, customer, client), daemon=True).start()


def _show_my_bookings(phone, client_id, customer_phone, client):
    apts = db_layer.get_customer_appointments(client_id, customer_phone)
    if not apts:
        wa.send_buttons(phone,
            "You don't have any appointments yet!",
            [{"id": "bk_services", "title": "📋 Book Now"}], client)
        return
    icons = {"pending": "⏳", "confirmed": "✅", "completed": "🎉", "cancelled": "❌"}
    text  = "📅 *Your Appointments*\n\n"
    for a in apts[:5]:
        icon  = icons.get(a.get("status", "pending"), "📋")
        text += f"{icon} *{a.get('ref')}*\n   {a.get('service_name','')} · {a.get('date','')} {a.get('time','')}\n\n"
    wa.send_text(phone, text.strip(), client)


def _get_slots(client):
    from templates_config import get_template
    t = get_template(client.get("template", "booking"))
    return t.get("booking_config", {}).get("time_slots", DEFAULT_SLOTS)


def _save(client_id, phone, session):
    threading.Thread(
        target=db_layer.save_session,
        args=(client_id, phone, session.get("state", "idle"),
              session.get("cart", {}), session.get("context", []),
              session.get("human_mode", False)),
        daemon=True
    ).start()
