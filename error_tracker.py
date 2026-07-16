# ══════════════════════════════════════════════════════
# JORDAN v5.6 — ERROR TRACKER & HEALTH MONITOR
# ══════════════════════════════════════════════════════

import os
import time
import json
import logging
import threading
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

# ── In-memory error store ──────────────────────────
MAX_ERRORS = 500
_error_lock = threading.Lock()
_errors = []  # list of {type, message, module, timestamp, count}

# ── Critical error webhook (optional) ──────────────
ALERT_WEBHOOK = os.environ.get("ALERT_WEBHOOK_URL", "")

# ── Error types we care about ──────────────────────
CRITICAL_TYPES = {
    "supabase_connection", "webhook_drop", "whatsapp_api_failure",
    "db_write_failure", "session_corruption"
}


def track(error_type: str, message: str, module: str = "system", critical: bool = False):
    """Record an error for monitoring. Deduplicates by type+message within 5 min."""
    now = datetime.utcnow()
    with _error_lock:
        for e in _errors:
            if (e["type"] == error_type and e["message"] == message and
                    (now - datetime.fromisoformat(e["timestamp"])).total_seconds() < 300):
                e["count"] += 1
                e["last_seen"] = now.isoformat()
                return

        entry = {
            "type": error_type,
            "message": message,
            "module": module,
            "timestamp": now.isoformat(),
            "last_seen": now.isoformat(),
            "count": 1
        }
        _errors.insert(0, entry)

        while len(_errors) > MAX_ERRORS:
            _errors.pop()

    level = logging.ERROR if critical or error_type in CRITICAL_TYPES else logging.WARNING
    logger.log(level, f"[Tracked] {error_type}: {message}")

    if critical and ALERT_WEBHOOK:
        _send_alert(entry)


def _send_alert(entry: dict):
    """Send a webhook alert for critical errors."""
    try:
        import urllib.request
        body = json.dumps({
            "text": f"🚨 Jordan Error: *{entry['type']}*\n"
                    f"Module: {entry['module']}\n"
                    f"Message: {entry['message']}\n"
                    f"Time: {entry['timestamp']}"
        }).encode()
        req = urllib.request.Request(ALERT_WEBHOOK, data=body,
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def get_recent_errors(minutes: int = 60, limit: int = 50) -> list:
    """Get errors from the last N minutes."""
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    with _error_lock:
        result = []
        for e in _errors:
            if datetime.fromisoformat(e["timestamp"]) >= cutoff:
                result.append(dict(e))
                if len(result) >= limit:
                    break
        return result


def get_error_summary() -> dict:
    """Return aggregate error stats."""
    now = datetime.utcnow()
    cutoff_1h = now - timedelta(hours=1)
    cutoff_24h = now - timedelta(hours=24)

    with _error_lock:
        total = len(_errors)
        last_1h = sum(1 for e in _errors
                      if datetime.fromisoformat(e["timestamp"]) >= cutoff_1h)
        last_24h = sum(1 for e in _errors
                       if datetime.fromisoformat(e["timestamp"]) >= cutoff_24h)
        by_type = defaultdict(int)
        for e in _errors:
            if datetime.fromisoformat(e["timestamp"]) >= cutoff_24h:
                by_type[e["type"]] += e["count"]

    return {
        "total_errors": total,
        "errors_last_hour": last_1h,
        "errors_last_24h": last_24h,
        "by_type": dict(by_type),
        "critical_count": sum(1 for e in _errors
                              if e["type"] in CRITICAL_TYPES),
    }


def check_db_health() -> dict:
    """Verify Supabase connectivity."""
    try:
        import database as db_layer
        start = time.time()
        clients = db_layer.get_all_clients()
        latency = round((time.time() - start) * 1000)
        return {
            "db": "ok",
            "latency_ms": latency,
            "clients": len(clients) if isinstance(clients, list) else "error"
        }
    except Exception as e:
        track("supabase_connection", str(e), "health", critical=True)
        return {"db": "error", "message": str(e)[:200]}


def check_whatsapp_health() -> dict:
    """Verify WhatsApp API is reachable (light check)."""
    try:
        import whatsapp as wa
        return {"whatsapp": "configured", "app_secret_set": bool(wa.APP_SECRET)}
    except Exception as e:
        return {"whatsapp": "error", "message": str(e)[:200]}


def full_health_check() -> dict:
    """Run all health checks."""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {
            **check_db_health(),
            **check_whatsapp_health(),
        },
        "errors": get_error_summary()
    }
