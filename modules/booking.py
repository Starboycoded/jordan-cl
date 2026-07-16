# ══════════════════════════════════════════════════════
# JORDAN v5.5 — BOOKING MODULE
# Handles: services, availability, appointments, status
# Used by: salon, clinic, booking, consultant templates
# Supports per-day schedules with break periods.
# ══════════════════════════════════════════════════════

import logging
import threading
from datetime import date, timedelta

import database as db_layer
import whatsapp as wa
import availability as avail

logger = logging.getLogger(__name__)

DEFAULT_SLOTS = [
    "9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM",
    "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM", "5:00 PM"
]

BUTTON_MAP = {
    "bk_services": "services",
    "bk_mybooks":  "my bookings",
    "bk_cancel":   "cancel booking",
    "bk_confirm":  "confirm booking",
}


def is_trigger(message: str, button_id: str) -> bool:
    """Check if this message should be handled by the booking module."""
    btn = (button_id or "").lower()
    msg = message.lower().strip()

    # Button-based triggers
    if btn in BUTTON_MAP or btn.startswith(("svc_", "date_", "time_", "bk_", "apt_", "cancel_apt_", "pick_cancel_", "confirm_cancel_")):
        return True

    # Text triggers — direct matches
    if msg in ("services", "book", "book appointment", "book now",
               "schedule", "schedule appointment", "new appointment",
               "my bookings", "my appointments", "appointments", "bookings",
               "hi", "hello", "hey", "start", "menu", "restart",
               "what do you offer", "what services", "show services"):
        return True

    # Partial matches — catch variations
    for phrase in ("book appointment", "book a", "schedule", "make appointment",
                   "new booking", "services", "my booking", "my appointment",
                   "cancel booking", "cancel appointment", "cancel my"):
        if phrase in msg:
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

    # Services list — text triggers (direct + partial matches)
    if msg in ("services", "book", "book appointment", "book now",
               "schedule", "schedule appointment", "new appointment",
               "what do you offer", "what services", "show services",
               "menu") or any(p in msg for p in ("book appointment", "book a",
               "schedule an", "make appointment", "new booking", "services")):
        _show_services(phone, client)
        return

    # My bookings
    if msg in ("my bookings", "my appointments", "bookings", "appointments") or \
       any(p in msg for p in ("my booking", "my appointment")):
        _show_my_bookings(phone, client_id, phone, client)
        return

    # Cancel — show active appointments to cancel
    if msg in ("cancel", "cancel booking", "cancel appointment", "cancel my booking") or \
       any(p in msg for p in ("cancel booking", "cancel appointment", "cancel my")):
        _show_cancel_options(phone, client_id, phone, client, customer)
        return

    # Cancel specific appointment by ref
    if btn.startswith("pick_cancel_"):
        ref = btn.replace("pick_cancel_", "")
        _show_cancel_confirm(phone, ref, client)
        return
    
    if btn.startswith("confirm_cancel_"):
        _cancel_appointment(phone, btn.replace("confirm_cancel_", ""), client, session, customer)
        return
    
    if btn.startswith("cancel_apt_"):
        _cancel_appointment(phone, btn.replace("cancel_apt_", ""), client, session, customer)
        return

    # Awaiting typed date
    if session.get("state") == "awaiting_date":
        _handle_typed_date(phone, message, client, session)
        return

    # Awaiting time selection (typed or numbered)
    if session.get("state") == "awaiting_time":
        _handle_typed_time(phone, message, client, session)
        return

    # Awaiting notes
    if session.get("state") == "awaiting_notes":
        session["booking"]["notes"] = message.strip()
        _save(client_id, phone, session)
        _show_booking_summary(phone, client, session)
        return

    # Fallback — show welcome
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
    bc        = _get_booking_config(client)
    days_ahead = bc.get("days_ahead", 14)

    # Find first 3 days with availability
    buttons = []
    for i in range(1, min(days_ahead + 1, 31)):
        if len(buttons) >= 3:
            break
        d = today + timedelta(days=i)
        day_slots = avail.get_slots_for_date(bc, d)
        if not day_slots:
            continue  # day closed or no slots configured
        avail_slots = avail.get_available_slots(client_id, d.isoformat(), day_slots)
        if avail_slots:
            buttons.append({"id": f"date_{d.isoformat()}", "title": d.strftime("%a %d %b")})

    if not buttons:
        wa.send_text(phone,
            "😔 No available slots in the next few weeks. Please contact us directly.", client)
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
    bc        = _get_booking_config(client)

    try:
        d_obj = date.fromisoformat(chosen_date)
        label = d_obj.strftime("%A, %d %B %Y")
    except Exception:
        d_obj = None
        label = chosen_date

    # Get slots for this specific date using per-day schedule
    if d_obj:
        all_day_slots = avail.get_slots_for_date(bc, d_obj)
    else:
        all_day_slots = bc.get("time_slots", DEFAULT_SLOTS)

    if not all_day_slots:
        # Day is closed (e.g., Sunday)
        day_name = d_obj.strftime("%A") if d_obj else chosen_date
        alternatives = avail.get_next_available(client_id, booking_config=bc,
                                                 start_date=d_obj)
        if alternatives:
            msg = f"📅 We're closed on *{day_name}*.\n\n✅ *Next available:*\n"
            for opt in alternatives[:3]:
                try:
                    lbl = date.fromisoformat(opt["date"]).strftime("%a %d %b")
                except Exception:
                    lbl = opt["date"]
                msg += f"📅 *{lbl}*: {' · '.join(opt['slots'][:3])}\n"
            msg += "\nReply with a date to continue."
        else:
            msg = f"📅 We're closed on *{day_name}*. Please try a different day."
        session["state"] = "awaiting_date"
        _save(client_id, phone, session)
        wa.send_text(phone, msg, client)
        return

    available = avail.get_available_slots(client_id, chosen_date, all_day_slots)

    session["booking"]["date"] = chosen_date
    session["booking"]["_available_slots"] = available  # for numbered selection
    session["state"]           = "awaiting_time"
    _save(client_id, phone, session)

    if not available:
        alternatives = avail.get_next_available(client_id, booking_config=bc,
                                                 start_date=d_obj)
        if alternatives:
            msg = f"😔 No available slots on *{label}*.\n\n✅ *Next available:*\n"
            for opt in alternatives[:3]:
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
    elif len(available) <= 10:
        rows = [{"id": f"time_{s.replace(' ','_')}", "title": s, "description": "Available"} for s in available]
        wa.send_list(phone,
            f"📅 *{label}* — {len(available)} available\n\nChoose your preferred time:",
            "Pick a Time",
            [{"title": "Available Times", "rows": rows}], client)
    else:
        # More than 10 slots — WhatsApp lists cap at 10 rows, use text instead
        text = f"📅 *{label}* — {len(available)} available\n\n"
        for i, s in enumerate(available[:15], 1):
            text += f"{i}. {s}\n"
        if len(available) > 15:
            text += f"\n_...and {len(available)-15} more_\n"
        text += "\nReply with your preferred time (e.g. *10:00 AM*)."
        wa.send_text(phone, text, client)


def _select_time(phone, time_label, client, session, customer):
    client_id  = str(client["id"])
    apt_date   = session.get("booking", {}).get("date", "")
    bc         = _get_booking_config(client)

    # Double-check availability
    if apt_date and not avail.is_slot_available(client_id, apt_date, time_label):
        try:
            d_obj = date.fromisoformat(apt_date)
        except Exception:
            d_obj = None
        if d_obj:
            all_day_slots = avail.get_slots_for_date(bc, d_obj)
        else:
            all_day_slots = bc.get("time_slots", DEFAULT_SLOTS)
        conflict_msg = avail.build_conflict_message(client_id, apt_date, time_label, 
                                                     all_day_slots, bc)
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


def _handle_typed_time(phone, message, client, session):
    """Handle typed time or numbered selection from the time list."""
    client_id = str(client["id"])
    bc        = _get_booking_config(client)
    msg       = message.strip()
    available = session.get("booking", {}).get("_available_slots", [])
    
    # Try numbered selection first (e.g., user types "3" for item #3)
    try:
        num = int(msg)
        if 1 <= num <= len(available):
            time_label = available[num - 1]
            _select_time(phone, time_label, client, session, {"name": ""})
            return
        else:
            wa.send_text(phone,
                f"Please pick a number between 1 and {len(available)}.\\n\\n"
                f"Or type a time like *10:00 AM*.", client)
            return
    except ValueError:
        pass  # not a number, try as time string
    
    # Try parsing as a time string (e.g., "10:00 AM", "2pm", "14:00")
    try:
        from dateutil import parser as dp
        import re
        # Clean up common formats
        clean = msg.upper().replace(" ", "").replace(".", ":")
        # Try to parse
        parsed = dp.parse(msg)
        hour = parsed.hour
        minute = parsed.minute
        # Format consistently
        if hour == 0:
            formatted = f"12:{minute:02d} AM"
        elif hour < 12:
            formatted = f"{hour}:{minute:02d} AM"
        elif hour == 12:
            formatted = f"12:{minute:02d} PM"
        else:
            formatted = f"{hour-12}:{minute:02d} PM"
        
        # Check if this time is in the available slots (fuzzy match)
        if available:
            # Try exact match first
            if formatted in available:
                _select_time(phone, formatted, client, session, {"name": ""})
                return
            # Try the raw message as-is
            if msg.upper() in [s.upper() for s in available]:
                _select_time(phone, msg.upper(), client, session, {"name": ""})
                return
        
        # If we got here, the time was parsed but not in available slots
        _select_time(phone, formatted, client, session, {"name": ""})
        return
    except Exception:
        pass
    
    # Can't parse — show help
    if available:
        text = "I didn't catch that time. \\n\\nPlease type a time like *10:00 AM* or pick a number from the list."
    else:
        text = "I didn't catch that time. Try something like *10:00 AM* or *2pm*."
    wa.send_text(phone, text, client)


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


def _show_cancel_options(phone, client_id, customer_phone, client, customer):
    """Show customer their active appointments and let them pick which to cancel."""
    currency = client.get("currency", "NGN")
    apts = db_layer.get_customer_appointments(client_id, customer_phone)
    active = [a for a in (apts or []) if a.get("status") in ("pending", "confirmed")]
    
    if not active:
        wa.send_buttons(phone,
            "You don't have any active appointments to cancel! 📋",
            [{"id": "bk_services", "title": "📋 Book Appointment"}], client)
        return
    
    if len(active) == 1:
        a = active[0]
        wa.send_buttons(phone,
            f"📋 *Cancel This Appointment?*\n\n"
            f"🔢 {a['ref']}\n"
            f"💆 {a['service_name']}\n"
            f"📅 {a['date']} at {a['time']}\n"
            f"💰 {currency} {int(float(a.get('price',0))):,}\n\n"
            f"Confirm cancellation?", 
            [{"id": f"cancel_apt_{a['ref']}", "title": "✅ Yes, Cancel It"},
             {"id": "bk_mybooks", "title": "↩ No, Keep It"}], client)
    else:
        # Multiple appointments — show as buttons
        buttons = []
        for a in active[:3]:
            label = f"{a['ref']} — {a['service_name'][:15]} ({a['date']})"
            buttons.append({"id": f"pick_cancel_{a['ref']}", "title": label[:20]})
        wa.send_buttons(phone,
            f"📋 You have {len(active)} active appointments. Tap one to review before cancelling:", 
            buttons, client)


def _show_cancel_confirm(phone, ref, client):
    """Show confirmation dialog before cancelling (multi-appointment flow)."""
    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")
    
    apts = db_layer.get_customer_appointments(client_id, phone)
    match = next((a for a in (apts or []) if a.get("ref", "").upper() == ref.upper()), None)
    
    if not match:
        wa.send_text(phone, 
            "I couldn't find that appointment. Type *MY BOOKINGS* to see your appointments.", 
            client)
        return
    
    wa.send_buttons(phone,
        f"\u2622\ufe0f *Cancel This Appointment?*\n\n"
        f"\U0001f522 {match['ref']}\n"
        f"\U0001f486 {match['service_name']}\n"
        f"\U0001f4c5 {match['date']} at {match['time']}\n"
        f"\U0001f4b0 {currency} {int(float(match.get('price',0))):,}\n\n"
        f"\u26a0\ufe0f This cannot be undone.",
        [{"id": f"confirm_cancel_{ref}", "title": "\u2705 Yes, Cancel It"},
         {"id": "bk_mybooks", "title": "\u21a9 No, Keep It"}], client)


def _cancel_appointment(phone, ref, client, session, customer):
    """Actually cancel an appointment by ref."""
    client_id = str(client["id"])
    currency  = client.get("currency", "NGN")
    
    # Verify this appointment belongs to this customer
    apts = db_layer.get_customer_appointments(client_id, phone)
    match = next((a for a in (apts or []) if a.get("ref", "").upper() == ref.upper()), None)
    
    if not match:
        wa.send_text(phone, 
            "I couldn't find that appointment. Type *MY BOOKINGS* to see your appointments.", 
            client)
        return
    
    ok = db_layer.update_appointment_status(ref, client_id, "cancelled")
    
    if ok:
        wa.send_text(phone,
            f"✅ *Appointment Cancelled*\n\n"
            f"🔢 {ref}\n"
            f"💆 {match['service_name']}\n"
            f"📅 {match['date']} at {match['time']}\n\n"
            f"Any time you need us, we're here! 😊", client)
    else:
        wa.send_text(phone,
            "Sorry, something went wrong. Please try again or contact us directly.", 
            client)


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


def _get_booking_config(client: dict) -> dict:
    """Get the booking config from the client's template."""
    from templates_config import get_template
    t = get_template(client.get("template", "booking"))
    return t.get("booking_config", {})


def _get_slots(client: dict, specific_date: date = None) -> list:
    """
    Get time slots for a client. If specific_date is provided and the template
    has a per-day schedule, returns slots for that day. Falls back to flat slots.
    """
    bc = _get_booking_config(client)
    if bc.get("schedule") and specific_date:
        return avail.get_slots_for_date(bc, specific_date)
    return bc.get("time_slots", DEFAULT_SLOTS)


def _save(client_id, phone, session):
    threading.Thread(
        target=db_layer.save_session,
        args=(client_id, phone, session.get("state", "idle"),
              session.get("cart", {}), session.get("context", []),
              session.get("human_mode", False)),
        daemon=True
    ).start()
