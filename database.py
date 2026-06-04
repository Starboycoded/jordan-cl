# ══════════════════════════════════════════════════════
# JORDAN v5 — DATABASE LAYER (Supabase)
# ══════════════════════════════════════════════════════

import os
import json
import logging
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
        r = db().table("clients").select("*").eq("active", True).execute()
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
        r = db().table("sessions").select("*").eq("client_id", client_id).eq("phone", phone).execute()
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
