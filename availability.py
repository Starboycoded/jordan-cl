# ══════════════════════════════════════════════════════
# JORDAN v5.3 — APPOINTMENT AVAILABILITY
# Prevents double bookings.
# Returns alternative slots when a conflict exists.
# ══════════════════════════════════════════════════════

import logging
from datetime import date, datetime, timedelta
from database import db

logger = logging.getLogger(__name__)


def is_slot_available(client_id: str, apt_date: str, apt_time: str,
                      exclude_ref: str = None) -> bool:
    """
    Returns True if the slot is free.
    exclude_ref lets you skip the current appointment when editing.
    Blocked statuses: pending, confirmed. (cancelled/no_show free the slot.)
    """
    try:
        q = db().table("appointments")\
            .select("id")\
            .eq("client_id", client_id)\
            .eq("date", apt_date)\
            .eq("time", apt_time)\
            .in_("status", ["pending", "confirmed"])

        if exclude_ref:
            q = q.neq("ref", exclude_ref)

        result = q.execute()
        return len(result.data or []) == 0
    except Exception as e:
        logger.error(f"[Availability] is_slot_available: {e}")
        return True     # fail open — don't block on DB error


def get_available_slots(client_id: str, apt_date: str,
                        all_slots: list) -> list:
    """
    Given a list of all configured time slots for a day,
    returns only the ones not yet booked.
    """
    try:
        result = db().table("appointments")\
            .select("time")\
            .eq("client_id", client_id)\
            .eq("date", apt_date)\
            .in_("status", ["pending", "confirmed"])\
            .execute()

        booked = {row["time"] for row in (result.data or [])}
        return [s for s in all_slots if s not in booked]
    except Exception as e:
        logger.error(f"[Availability] get_available_slots: {e}")
        return all_slots    # fail open


def get_next_available(client_id: str, all_slots: list,
                       days_ahead: int = 7,
                       start_date: date = None) -> list:
    """
    Scans the next `days_ahead` days and returns a list of
    (date_str, available_slots) tuples that have at least one free slot.
    Useful for suggesting alternatives when the chosen slot is taken.
    """
    results  = []
    start    = start_date or date.today()

    for i in range(1, days_ahead + 1):
        d         = start + timedelta(days=i)
        d_str     = d.isoformat()
        available = get_available_slots(client_id, d_str, all_slots)
        if available:
            results.append({"date": d_str, "slots": available})
        if len(results) >= 3:   # return first 3 days with availability
            break

    return results


def build_conflict_message(client_id: str, apt_date: str, apt_time: str,
                           all_slots: list) -> str:
    """
    Build a helpful message when the requested slot is taken,
    suggesting the next available options.
    """
    # Try other slots on the same day first
    same_day = get_available_slots(client_id, apt_date, all_slots)
    if same_day:
        slots_text = " · ".join(same_day[:4])
        try:
            label = date.fromisoformat(apt_date).strftime("%A %d %b")
        except Exception:
            label = apt_date
        return (
            f"😔 *{apt_time}* on {label} is already booked.\n\n"
            f"✅ Still available on {label}:\n{slots_text}\n\n"
            f"Reply with your preferred time to continue."
        )

    # No slots on that day — suggest next available days
    alternatives = get_next_available(client_id, all_slots,
                                      start_date=date.fromisoformat(apt_date)
                                      if apt_date else None)
    if not alternatives:
        return (
            f"😔 *{apt_time}* is already booked and we have no "
            f"available slots in the next 7 days. "
            f"Please contact us directly to arrange an appointment."
        )

    msg = f"😔 *{apt_time}* is already booked.\n\n✅ *Next available:*\n"
    for opt in alternatives:
        try:
            label = date.fromisoformat(opt["date"]).strftime("%a %d %b")
        except Exception:
            label = opt["date"]
        slots_preview = " · ".join(opt["slots"][:3])
        msg += f"📅 *{label}*: {slots_preview}\n"

    msg += "\nReply with a date and time to book."
    return msg
