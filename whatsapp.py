# ═════════════════════════════════════════════════════
# JORDAN v5 — WHATSAPP META CLOUD API HANDLER
# ═════════════════════════════════════════════════════

import os
import hmac as _hmac
import hashlib
import logging
import requests

logger = logging.getLogger(__name__)

WA_API_VERSION   = "v20.0"
WA_BASE_URL      = f"https://graph.facebook.com/{WA_API_VERSION}"
APP_SECRET       = os.environ.get("APP_SECRET", "")       # For webhook signature verification
WHATSAPP_TOKEN   = os.environ.get("WHATSAPP_TOKEN", "")   # Fallback global token
PHONE_NUMBER_ID  = os.environ.get("PHONE_NUMBER_ID", "")  # Fallback global phone number ID


def _headers(token: str = None) -> dict:
    return {
        "Authorization": f"Bearer {token or WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }


def _phone_id(client: dict) -> str:
    return client.get("phone_number_id") or PHONE_NUMBER_ID


def _token(client: dict) -> str:
    return client.get("wa_token") or WHATSAPP_TOKEN


# ─────────────────────────────────────────────────────
# SEND MESSAGES
# ─────────────────────────────────────────────────────

def send_text(to: str, body: str, client: dict) -> bool:
    """Send a plain text message."""
    if not body or not to:
        return False
    url     = f"{WA_BASE_URL}/{_phone_id(client)}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                to,
        "type":              "text",
        "text":              {"preview_url": False, "body": body[:4096]}
    }
    try:
        r = requests.post(url, json=payload, headers=_headers(_token(client)), timeout=10)
        if r.status_code != 200:
            logger.warning(f"[WA] send_text failed {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.error(f"[WA] send_text exception: {e}")
        return False


def send_buttons(to: str, body: str, buttons: list[dict], client: dict) -> bool:
    """
    Send interactive reply buttons (max 3).
    buttons = [{"id": "btn_yes", "title": "Yes"}, ...]
    """
    if not buttons:
        return send_text(to, body, client)

    buttons = buttons[:3]
    url     = f"{WA_BASE_URL}/{_phone_id(client)}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                to,
        "type":              "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"][:20]}}
                    for b in buttons
                ]
            }
        }
    }
    try:
        r = requests.post(url, json=payload, headers=_headers(_token(client)), timeout=10)
        if r.status_code != 200:
            logger.warning(f"[WA] send_buttons failed {r.status_code}: {r.text[:200]}")
            return send_text(to, body, client)  # Fallback to plain text
        return True
    except Exception as e:
        logger.error(f"[WA] send_buttons exception: {e}")
        return False


def send_list(to: str, body: str, button_label: str, sections: list[dict], client: dict) -> bool:
    """
    Send interactive list message.
    sections = [{"title": "Products", "rows": [{"id": "p_1", "title": "Bag", "description": "NGN 5,000"}]}]
    """
    url     = f"{WA_BASE_URL}/{_phone_id(client)}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                to,
        "type":              "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body[:1024]},
            "action": {
                "button": button_label[:20],
                "sections": sections
            }
        }
    }
    # Safety: cap each section at 10 rows (WhatsApp limit)
    for section in sections:
        rows = section.get("rows", [])
        if len(rows) > 10:
            logger.warning(f"[WA] send_list: capping {len(rows)} rows to 10")
            section["rows"] = rows[:10]

    try:
        r = requests.post(url, json=payload, headers=_headers(_token(client)), timeout=10)
        if r.status_code != 200:
            logger.warning(f"[WA] send_list failed {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.error(f"[WA] send_list exception: {e}")
        return False


def send_image(to: str, image_url: str, caption: str, client: dict) -> bool:
    """Send image with caption."""
    url     = f"{WA_BASE_URL}/{_phone_id(client)}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to":   to,
        "type": "image",
        "image": {"link": image_url, "caption": caption[:1024]}
    }
    try:
        r = requests.post(url, json=payload, headers=_headers(_token(client)), timeout=10)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"[WA] send_image exception: {e}")
        return False


def mark_read(message_id: str, client: dict) -> None:
    """Mark a message as read (shows blue ticks)."""
    url     = f"{WA_BASE_URL}/{_phone_id(client)}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "status":            "read",
        "message_id":        message_id
    }
    try:
        requests.post(url, json=payload, headers=_headers(_token(client)), timeout=5)
    except:
        pass


# ─────────────────────────────────────────────────────
# PARSE INCOMING WEBHOOK
# ─────────────────────────────────────────────────────

def parse_webhook(data: dict) -> Optional[dict]:
    """
    Parse Meta webhook payload.
    Returns dict with: phone, message_id, type, text, button_id, client_phone_id
    Returns None if not a valid user message.
    """
    try:
        entry   = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value   = changes.get("value", {})

        # Get the phone number ID this message came into
        metadata       = value.get("metadata", {})
        client_phone_id = metadata.get("phone_number_id", "")

        messages = value.get("messages", [])
        if not messages:
            return None

        msg = messages[0]
        msg_type   = msg.get("type", "")
        message_id = msg.get("id", "")
        phone      = msg.get("from", "")

        if not phone:
            return None

        result = {
            "phone":           phone,
            "message_id":      message_id,
            "type":            msg_type,
            "text":            None,
            "button_id":       None,
            "client_phone_id": client_phone_id
        }

        if msg_type == "text":
            result["text"] = msg.get("text", {}).get("body", "").strip()

        elif msg_type == "interactive":
            interactive = msg.get("interactive", {})
            sub_type    = interactive.get("type", "")
            if sub_type == "button_reply":
                result["button_id"] = interactive["button_reply"].get("id", "")
                result["text"]      = interactive["button_reply"].get("title", "")
            elif sub_type == "list_reply":
                result["button_id"] = interactive["list_reply"].get("id", "")
                result["text"]      = interactive["list_reply"].get("title", "")

        elif msg_type == "audio":
            result["text"] = "[voice_note]"

        elif msg_type == "image":
            result["text"] = "[image]"

        return result

    except Exception as e:
        logger.error(f"[WA] parse_webhook: {e}")
        return None


def verify_signature(payload: bytes, signature: str) -> bool:
    if not APP_SECRET:
        return True
    try:
        expected = "sha256=" + _hmac.new(
            APP_SECRET.encode(), payload, hashlib.sha256
        ).hexdigest()
        return _hmac.compare_digest(expected, signature)
    except Exception as e:
        logger.error(f"[WA] verify_signature: {e}")
        return False


# ─────────────────────────────────────────────────────
# BROADCAST HELPER
# ─────────────────────────────────────────────────────

def broadcast_to_customers(customers: list[dict], message: str, client: dict,
                            delay: float = 1.2, hourly_limit: int = 80) -> tuple[int, int]:
    """
    Send a message to a list of customers with rate limiting.
    Returns (sent, failed).
    """
    import time
    sent, failed, hourly = 0, 0, 0

    for cust in customers:
        phone = cust.get("phone", "")
        if not phone:
            continue
        if hourly >= hourly_limit:
            logger.warning("[WA] Hourly broadcast limit reached. Stopping.")
            break

        ok = send_text(phone, message, client)
        if ok:
            sent   += 1
            hourly += 1
        else:
            failed += 1

        time.sleep(delay)

    return sent, failed


# Resolve Optional import
from typing import Optional
