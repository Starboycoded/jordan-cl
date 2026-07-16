# ══════════════════════════════════════════════════════
# JORDAN v5 — DATABASE LAYER (Supabase)
# ══════════════════════════════════════════════════════

import os
import json
import logging
import time
from datetime import date
from typing import Optional
from supabase import create_client, Client

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")   # service_role key (server-side only)

_client: Optional[Client] = None


def db() -> Client:
    """Return singleton Supabase client."""
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set.")
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def _retry(fn, max_retries=3, base_delay=0.5):
    """Retry a callable with exponential-ish backoff for transient Supabase errors."""
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            # Only retry on transient errors (network, timeout, resource unavailable)
            is_transient = any(kw in err_str for kw in [
                "errno 11", "resource temporarily unavailable",
                "timeout", "connection", "network", "too many requests",
                "503", "502", "504", "429"
            ])
            if not is_transient or attempt >= max_retries:
                raise
            delay = base_delay * (attempt + 1)
            logger.warning(f"[DB] _retry attempt {attempt+1}/{max_retries} after {delay}s: {e}")
            time.sleep(delay)
    raise last_err


# ─────────────────────────────────────────────────────
# CLIENTS
# ─────────────────────────────────────────────────────

def get_client_by_slug(slug: str) -> Optional[dict]:
    try:
        r = db().table("clients").select("*").eq("slug", slug).eq("active", True).single().execute()
        return r.data
    except Exception as e:
        logger.error(f"[DB] get_client_by_slug({slug}): {e}")
        return None


def get_all_clients() -> list:
    try:
        r = _retry(lambda: db().table("clients").select("*").eq("active", True).execute())
        return r.data or []
    except Exception as e:
        logger.error(f"[DB] get_all_clients: {e}")
        return []


def create_client_record(slug: str, business_name: str, template: str = "general",
                          currency: str = "NGN", phone_number_id: str = "") -> Optional[dict]:
    try:
        r = db().table("clients").insert({
            "slug": slug,
            "business_name": business_name,
            "template": template,
            "currency": currency,
            "phone_number_id": phone_number_id
        }).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.error(f"[DB] create_client_record: {e}")
        return None


def update_client(client_id: str, updates: dict) -> bool:
    try:
        db().table("clients").update(updates).eq("id", client_id).execute()
        return True
    except Exception as e:
        logger.error(f"[DB] update_client: {e}")
        return False


# ─────────────────────────────────────────────────────
# PRODUCTS
# ─────────────────────────────────────────────────────

def get_products(client_id: str) -> list:
    try:
        r = db().table("products").select("*").eq("client_id", client_id).eq("active", True).order("id").execute()
        return r.data or []
    except Exception as e:
        logger.error(f"[DB] get_products: {e}")
        return []


def get_product(product_id: int, client_id: str) -> Optional[dict]:
    try:
        r = db().table("products").select("*").eq("id", product_id).eq("client_id", client_id).single().execute()
        return r.data
    except Exception as e:
        logger.error(f"[DB] get_product: {e}")
        return None


def create_product(client_id: str, name: str, price: float, description: str = "",
                   stock: int = 0, image_url: str = "", category: str = "") -> Optional[dict]:
    try:
        r = db().table("products").insert({
            "client_id": client_id,
            "name": name,
            "price": price,
            "description": description,
            "stock": stock,
            "image_url": image_url,
            "category": category
        }).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.error(f"[DB] create_product: {e}")
        return None


def update_product(product_id: int, client_id: str, updates: dict) -> bool:
    try:
        db().table("products").update(updates).eq("id", product_id).eq("client_id", client_id).execute()
        return True
    except Exception as e:
        logger.error(f"[DB] update_product: {e}")
        return False


def delete_product(product_id: int, client_id: str) -> bool:
    """Soft delete."""
    return update_product(product_id, client_id, {"active": False})


def decrement_stock(product_id: int, client_id: str, qty: int) -> bool:
    try:
        prod = get_product(product_id, client_id)
        if not prod:
            return False
        new_stock = max(0, int(prod.get("stock", 0)) - qty)
        return update_product(product_id, client_id, {"stock": new_stock})
    except Exception as e:
        logger.error(f"[DB] decrement_stock: {e}")
        return False


# ─────────────────────────────────────────────────────
# CUSTOMERS
# ─────────────────────────────────────────────────────

def get_or_create_customer(client_id: str, phone: str) -> dict:
    try:
        r = db().table("customers").select("*").eq("client_id", client_id).eq("phone", phone).execute()
        if r.data:
            # Update last_seen
            db().table("customers").update({"last_seen": "now()"}).eq("id", r.data[0]["id"]).execute()
            return r.data[0]
        # Create new
        r2 = db().table("customers").insert({
            "client_id": client_id,
            "phone": phone
        }).execute()
        return r2.data[0] if r2.data else {"phone": phone, "client_id": client_id}
    except Exception as e:
        logger.error(f"[DB] get_or_create_customer: {e}")
        return {"phone": phone, "client_id": client_id}


def update_customer(customer_id: int, updates: dict) -> bool:
    try:
        db().table("customers").update(updates).eq("id", customer_id).execute()
        return True
    except Exception as e:
        logger.error(f"[DB] update_customer: {e}")
        return False


def get_all_customers(client_id: str) -> list:
    try:
        r = db().table("customers").select("phone, name").eq("client_id", client_id).execute()
        return r.data or []
    except Exception as e:
        logger.error(f"[DB] get_all_customers: {e}")
        return []


# ─────────────────────────────────────────────────────
# ORDERS
# ─────────────────────────────────────────────────────

def generate_order_ref(client_id: str) -> str:
    today = date.today().strftime("%Y%m%d")
    try:
        r = db().table("orders").select("id", count="exact").eq("client_id", client_id).execute()
        count = (r.count or 0) + 1
        return f"ORD-{today}-{count:04d}"
    except:
        import random
        return f"ORD-{today}-{random.randint(1000,9999)}"


def create_order(client_id: str, phone: str, items: list,
                 total: float, address: str = "", customer_id: int = None) -> Optional[dict]:
    try:
        order_ref = generate_order_ref(client_id)
        r = db().table("orders").insert({
            "client_id": client_id,
            "order_ref": order_ref,
            "customer_id": customer_id,
            "phone": phone,
            "items": items,
            "total": total,
            "address": address,
            "status": "pending"
        }).execute()

        # Update customer stats
        if customer_id:
            cust_r = db().table("customers").select("total_spend, order_count").eq("id", customer_id).single().execute()
            if cust_r.data:
                db().table("customers").update({
                    "total_spend": float(cust_r.data.get("total_spend", 0)) + total,
                    "order_count": int(cust_r.data.get("order_count", 0)) + 1,
                    "last_seen": "now()"
                }).eq("id", customer_id).execute()

        return r.data[0] if r.data else None
    except Exception as e:
        logger.error(f"[DB] create_order: {e}")
        return None


def get_orders(client_id: str, limit: int = 100, status: str = None) -> list:
    try:
        q = db().table("orders").select("*").eq("client_id", client_id).order("created_at", desc=True).limit(limit)
        if status:
            q = q.eq("status", status)
        r = q.execute()
        return r.data or []
    except Exception as e:
        logger.error(f"[DB] get_orders: {e}")
        return []


def update_order_status(order_ref: str, client_id: str, status: str) -> bool:
    try:
        db().table("orders").update({
            "status": status,
            "updated_at": "now()"
        }).eq("order_ref", order_ref).eq("client_id", client_id).execute()
        return True
    except Exception as e:
        logger.error(f"[DB] update_order_status: {e}")
        return False


def get_customer_orders(client_id: str, phone: str) -> list:
    try:
        r = db().table("orders").select("order_ref, items, total, status, created_at")\
            .eq("client_id", client_id).eq("phone", phone)\
            .order("created_at", desc=True).limit(5).execute()
        return r.data or []
    except Exception as e:
        logger.error(f"[DB] get_customer_orders: {e}")
        return []


# ─────────────────────────────────────────────────────
# SESSIONS
# ─────────────────────────────────────────────────────

def get_session(client_id: str, phone: str) -> dict:
    try:
        r = _retry(lambda: db().table("sessions").select("*").eq("client_id", client_id).eq("phone", phone).execute())
        if r.data:
            return r.data[0]
        return {"client_id": client_id, "phone": phone, "state": "idle", "cart": {}, "context": [], "human_mode": False}
    except Exception as e:
        logger.error(f"[DB] get_session: {e}")
        return {"client_id": client_id, "phone": phone, "state": "idle", "cart": {}, "context": [], "human_mode": False}


def save_session(client_id: str, phone: str, state: str, cart: dict,
                 context: list, human_mode: bool = False) -> bool:
    try:
        db().table("sessions").upsert({
            "client_id": client_id,
            "phone": phone,
            "state": state,
            "cart": cart,
            "context": context[-20:],   # keep last 20 messages
            "human_mode": human_mode,
            "updated_at": "now()"
        }, on_conflict="client_id,phone").execute()
        return True
    except Exception as e:
        logger.error(f"[DB] save_session: {e}")
        return False


# ─────────────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────────────

def get_analytics(client_id: str) -> dict:
    try:
        orders_r  = db().table("orders").select("status, total").eq("client_id", client_id).execute()
        orders    = orders_r.data or []
        customers = db().table("customers").select("id", count="exact").eq("client_id", client_id).execute()
        products  = db().table("products").select("name, stock").eq("client_id", client_id).eq("active", True).execute()

        total_orders   = len(orders)
        pending        = sum(1 for o in orders if o.get("status") == "pending")
        delivered      = sum(1 for o in orders if o.get("status") == "delivered")
        revenue        = sum(float(o.get("total", 0)) for o in orders if o.get("status") == "delivered")
        total_customers = customers.count or 0
        low_stock      = [p["name"] for p in (products.data or []) if int(p.get("stock", 0)) <= 3]

        return {
            "total_orders": total_orders,
            "pending": pending,
            "delivered": delivered,
            "revenue": revenue,
            "total_customers": total_customers,
            "low_stock": low_stock,
            "inventory": products.data or []
        }
    except Exception as e:
        logger.error(f"[DB] get_analytics: {e}")
        return {"total_orders": 0, "pending": 0, "delivered": 0,
                "revenue": 0, "total_customers": 0, "low_stock": [], "inventory": []}


def log_tokens(client_id: str, tokens: int) -> None:
    try:
        today = date.today().isoformat()
        db().rpc("increment_tokens", {"p_client_id": client_id, "p_date": today, "p_tokens": tokens}).execute()
    except:
        pass  # Non-critical


def get_tokens_today(client_id: str) -> int:
    try:
        today = date.today().isoformat()
        r = db().table("token_log").select("tokens").eq("client_id", client_id).eq("date", today).execute()
        return r.data[0]["tokens"] if r.data else 0
    except:
        return 0


# ─────────────────────────────────────────────────────
# APPOINTMENTS (Booking template)
# ─────────────────────────────────────────────────────

def create_appointment(client_id: str, phone: str, service_name: str,
                       service_id: str = None, price: float = 0,
                       date: str = "", time: str = "",
                       notes: str = "", customer_id: int = None) -> Optional[dict]:
    try:
        from datetime import date as dt
        today = dt.today().strftime("%Y%m%d")
        count_r = db().table("appointments").select("id", count="exact").eq("client_id", client_id).execute()
        count   = (count_r.count or 0) + 1
        ref     = f"APT-{today}-{count:04d}"

        r = db().table("appointments").insert({
            "client_id":    client_id,
            "ref":          ref,
            "phone":        phone,
            "customer_id":  customer_id,
            "service_name": service_name,
            "service_id":   service_id,
            "price":        price,
            "date":         date,
            "time":         time,
            "notes":        notes,
            "status":       "pending"
        }).execute()
        return r.data[0] if r.data else {"ref": ref}
    except Exception as e:
        logger.error(f"[DB] create_appointment: {e}")
        return None


def get_appointments(client_id: str, limit: int = 100, status: str = None) -> list:
    try:
        q = db().table("appointments").select("*").eq("client_id", client_id)\
            .order("date", desc=True).limit(limit)
        if status:
            q = q.eq("status", status)
        return q.execute().data or []
    except Exception as e:
        logger.error(f"[DB] get_appointments: {e}")
        return []


def get_customer_appointments(client_id: str, phone: str) -> list:
    try:
        r = db().table("appointments").select("*")\
            .eq("client_id", client_id).eq("phone", phone)\
            .order("date", desc=True).limit(5).execute()
        return r.data or []
    except Exception as e:
        logger.error(f"[DB] get_customer_appointments: {e}")
        return []


def update_appointment_status(ref: str, client_id: str, status: str) -> bool:
    try:
        db().table("appointments").update({"status": status})\
            .eq("ref", ref).eq("client_id", client_id).execute()
        return True
    except Exception as e:
        logger.error(f"[DB] update_appointment_status: {e}")
        return False


# ─────────────────────────────────────────────────────
# LEADS (Lead Gen template)
# ─────────────────────────────────────────────────────

def create_lead(client_id: str, phone: str, data: dict,
                customer_id: int = None) -> Optional[dict]:
    try:
        from datetime import date as dt
        today = dt.today().strftime("%Y%m%d")
        count_r = db().table("leads").select("id", count="exact").eq("client_id", client_id).execute()
        count   = (count_r.count or 0) + 1
        ref     = f"LEAD-{today}-{count:04d}"

        r = db().table("leads").insert({
            "client_id":   client_id,
            "ref":         ref,
            "phone":       phone,
            "customer_id": customer_id,
            "name":        data.get("name", ""),
            "location":    data.get("location", ""),
            "budget":      data.get("budget", ""),
            "timeline":    data.get("timeline", ""),
            "interest":    data.get("interest", ""),
            "data":        data,
            "status":      "new"
        }).execute()
        return r.data[0] if r.data else {"ref": ref}
    except Exception as e:
        logger.error(f"[DB] create_lead: {e}")
        return None


def get_leads(client_id: str, limit: int = 100, status: str = None) -> list:
    try:
        q = db().table("leads").select("*").eq("client_id", client_id)\
            .order("created_at", desc=True).limit(limit)
        if status:
            q = q.eq("status", status)
        return q.execute().data or []
    except Exception as e:
        logger.error(f"[DB] get_leads: {e}")
        return []


def update_lead_status(ref: str, client_id: str, status: str) -> bool:
    try:
        db().table("leads").update({"status": status})\
            .eq("ref", ref).eq("client_id", client_id).execute()
        return True
    except Exception as e:
        logger.error(f"[DB] update_lead_status: {e}")
        return False


# ─────────────────────────────────────────────────────
# FAQS (Support template)
# ─────────────────────────────────────────────────────

def get_faqs(client_id: str) -> list:
    try:
        r = db().table("faqs").select("*").eq("client_id", client_id)\
            .eq("active", True).order("sort_order").execute()
        return r.data or []
    except Exception as e:
        logger.error(f"[DB] get_faqs: {e}")
        return []


def create_faq(client_id: str, question: str, answer: str,
               sort_order: int = 0) -> Optional[dict]:
    try:
        r = db().table("faqs").insert({
            "client_id":  client_id,
            "question":   question,
            "answer":     answer,
            "sort_order": sort_order,
            "active":     True
        }).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.error(f"[DB] create_faq: {e}")
        return None


def update_faq(faq_id: int, client_id: str, updates: dict) -> bool:
    try:
        db().table("faqs").update(updates)\
            .eq("id", faq_id).eq("client_id", client_id).execute()
        return True
    except Exception as e:
        logger.error(f"[DB] update_faq: {e}")
        return False


def delete_faq(faq_id: int, client_id: str) -> bool:
    return update_faq(faq_id, client_id, {"active": False})

# ─────────────────────────────────────────────────────
# MESSAGE INBOX (v5.6)
# ─────────────────────────────────────────────────────

def log_message(client_id: str, phone: str, direction: str, 
                message: str, message_id: str = None,
                sender_type: str = "customer") -> bool:
    """Log a WhatsApp message to the inbox."""
    try:
        record = {
            "client_id":   client_id,
            "phone":       phone,
            "direction":   direction,
            "message":     message[:4000],  # safety cap
            "sender_type": sender_type,
        }
        if message_id:
            record["message_id"] = message_id

        db().table("messages").upsert(
            record,
            on_conflict="client_id,message_id"
        ).execute()
        return True
    except Exception as e:
        # Don't fail the whole flow over a log failure
        logger.warning(f"[DB] log_message: {e}")
        return False


def get_messages(client_id: str, phone: str = None, 
                 limit: int = 100) -> list:
    """Get message history. If phone is provided, get that conversation."""
    try:
        q = db().table("messages").select("*")\
            .eq("client_id", client_id)\
            .order("created_at", desc=False)\
            .limit(limit)
        if phone:
            q = q.eq("phone", phone)
        return q.execute().data or []
    except Exception as e:
        logger.error(f"[DB] get_messages: {e}")
        return []


def get_conversation_list(client_id: str) -> list:
    """Get list of unique phone numbers with latest message preview."""
    try:
        # Get all messages, group by phone in Python
        r = db().table("messages").select("phone, message, direction, sender_type, created_at")\
            .eq("client_id", client_id)\
            .order("created_at", desc=True)\
            .limit(500)\
            .execute()

        if not r.data:
            return []

        # Group latest per phone
        seen = {}
        for msg in r.data:
            phone = msg["phone"]
            if phone not in seen:
                seen[phone] = {
                    "phone": phone,
                    "last_message": msg["message"][:100],
                    "last_direction": msg["direction"],
                    "last_sender": msg["sender_type"],
                    "last_at": msg["created_at"],
                }

        # Sort by most recent
        result = sorted(seen.values(), key=lambda x: x["last_at"], reverse=True)
        return result
    except Exception as e:
        logger.error(f"[DB] get_conversation_list: {e}")
        return []


def get_human_mode_session(client_id: str) -> dict:
    """Find a customer session that has human_mode active. Returns None if none."""
    try:
        r = db().table("sessions").select("*")\
            .eq("client_id", client_id)\
            .eq("human_mode", True)\
            .order("updated_at", desc=True)\
            .limit(1)\
            .execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.error(f"[DB] get_human_mode_session: {e}")
        return None


def end_human_mode(client_id: str, phone: str) -> bool:
    """Turn off human_mode for a customer session."""
    try:
        db().table("sessions").update({
            "human_mode": False,
            "updated_at": "now()"
        }).eq("client_id", client_id).eq("phone", phone).execute()
        return True
    except Exception as e:
        logger.error(f"[DB] end_human_mode: {e}")
        return False
