# ══════════════════════════════════════════════════════
# JORDAN v5.5 — APPOINTMENT AVAILABILITY
# Prevents double bookings.
# Supports per-day schedules with break periods.
# Returns alternative slots when a conflict exists.
# ══════════════════════════════════════════════════════

import logging
import re
from datetime import date, datetime, timedelta
from database import db

logger = logging.getLogger(__name__)


# ── TIME HELPERS ────────────────────────────────────

def _parse_time_str(time_str: str) -> tuple:
    """
    Parse a time string like '8:00 AM' or '1:30 PM' into (hours, minutes).
    Returns (hours_24h, minutes). Returns None on parse failure.
    """
    time_str = time_str.strip().upper()
    m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str)
    if not m:
        return None
    h = int(m.group(1))
    mm = int(m.group(2))
    ampm = m.group(3)
    if ampm == 'PM' and h != 12:
        h += 12
    elif ampm == 'AM' and h == 12:
        h = 0
    return (h, mm)


def _time_to_minutes(time_str: str) -> int:
    """Convert a time string like '8:00 AM' to minutes since midnight."""
    parsed = _parse_time_str(time_str)
    if parsed is None:
        return 0
    return parsed[0] * 60 + parsed[1]


def _minutes_to_time_str(minutes: int) -> str:
    """Convert minutes since midnight to a time string like '8:00 AM'."""
    h = (minutes // 60) % 24
    m = minutes % 60
    if h == 0:
        return f"12:{m:02d} AM"
    elif h < 12:
        return f"{h}:{m:02d} AM"
    elif h == 12:
        return f"12:{m:02d} PM"
    else:
        return f"{h - 12}:{m:02d} PM"


# ── SCHEDULE-BASED SLOT GENERATION ──────────────────

def generate_slots_from_day_config(day_config: dict, slot_duration: int = 60) -> list:
    """
    Generate time slots for a single day's schedule config.
    
    day_config: {'start': '8:00 AM', 'end': '5:00 PM', 
                 'breaks': [('1:00 PM', '2:00 PM')]}
    or None/empty → day is closed.
    
    Returns list of time strings like ['8:00 AM', '9:00 AM', ...]
    excluding break periods.
    """
    if not day_config or not day_config.get('start') or not day_config.get('end'):
        return []
    
    start_min = _time_to_minutes(day_config['start'])
    end_min   = _time_to_minutes(day_config['end'])
    breaks    = day_config.get('breaks', [])
    
    # Build break ranges in minutes
    break_ranges = []
    for b in breaks:
        if isinstance(b, (list, tuple)) and len(b) == 2:
            bs = _time_to_minutes(b[0])
            be = _time_to_minutes(b[1])
            break_ranges.append((bs, be))
    
    slots = []
    current = start_min
    while current + slot_duration <= end_min:
        time_str = _minutes_to_time_str(current)
        # Check if this slot falls within a break
        in_break = False
        for bs, be in break_ranges:
            if current < be and (current + slot_duration) > bs:
                in_break = True
                break
        
        if not in_break:
            slots.append(time_str)
        
        current += slot_duration
    
    return slots


def get_slots_for_date(booking_config: dict, date_obj: date) -> list:
    """
    Get the time slots available for a specific date based on the schedule config.
    
    booking_config: the full booking_config dict from the template.
    date_obj: a datetime.date object.
    
    Returns list of time strings (e.g., ['8:00 AM', '8:30 AM', ...]).
    Falls back to flat 'time_slots' if no schedule is configured.
    """
    schedule      = booking_config.get('schedule')
    slot_duration = booking_config.get('slot_duration', 60)
    time_slots    = booking_config.get('time_slots', [])
    
    if not schedule:
        # No per-day schedule — use legacy flat slots
        return time_slots
    
    # Map weekday number (0=Monday, 6=Sunday) to day name
    day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 
                 'friday', 'saturday', 'sunday']
    day_name  = day_names[date_obj.weekday()]
    
    day_config = schedule.get(day_name)
    
    if day_config is None:
        # Day explicitly set to null → closed
        return []
    
    if isinstance(day_config, dict):
        # Per-day config with start/end/breaks
        return generate_slots_from_day_config(day_config, slot_duration)
    
    # Fallback
    return time_slots


def get_all_slots_for_day(booking_config: dict, date_obj: date) -> list:
    """
    Get ALL configured slots for a date (before filtering booked ones).
    This is the total capacity for that day.
    """
    return get_slots_for_date(booking_config, date_obj)


# ── AVAILABILITY CHECKS ─────────────────────────────

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


def get_next_available(client_id: str, booking_config: dict = None,
                       days_ahead: int = 14,
                       start_date: date = None) -> list:
    """
    Scans the next `days_ahead` days and returns a list of
    (date_str, available_slots) tuples that have at least one free slot.
    
    If booking_config has a schedule, uses per-day slots.
    Falls back to flat time_slots otherwise.
    """
    results  = []
    start    = start_date or date.today()
    bc       = booking_config or {}
    flat_slots = bc.get('time_slots', [])

    for i in range(1, days_ahead + 1):
        d     = start + timedelta(days=i)
        d_str = d.isoformat()
        
        # Get slots for this specific date
        if bc.get('schedule'):
            all_day_slots = get_slots_for_date(bc, d)
        else:
            all_day_slots = flat_slots
        
        if not all_day_slots:
            continue  # day is closed
        
        available = get_available_slots(client_id, d_str, all_day_slots)
        if available:
            results.append({"date": d_str, "slots": available})
        if len(results) >= 3:   # return first 3 days with availability
            break

    return results


def build_conflict_message(client_id: str, apt_date: str, apt_time: str,
                           all_slots: list, booking_config: dict = None) -> str:
    """
    Build a helpful message when the requested slot is taken,
    suggesting the next available options.
    """
    bc = booking_config or {}
    
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
    alternatives = get_next_available(client_id, booking_config=bc,
                                      start_date=date.fromisoformat(apt_date)
                                      if apt_date else None)
    if not alternatives:
        return (
            f"😔 *{apt_time}* is already booked and we have no "
            f"available slots in the next 14 days. "
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
