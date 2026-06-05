# ══════════════════════════════════════════════════════
# JORDAN v5.3 — SUBSCRIPTION PLANS & FEATURE GATING
# All feature access checks go through this module.
# Never check plan strings directly in other files.
# ══════════════════════════════════════════════════════

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# PLAN DEFINITIONS
# ─────────────────────────────────────────────────────

PLANS = {
    "starter": {
        "name":         "Starter",
        "price_ngn":    15000,
        "description":  "One flow, basic dashboard",
        "features": {
            # Flows — only ONE allowed on starter
            "commerce":         True,
            "booking":          True,
            "lead_gen":         True,
            "support_template": True,   # support as main template
            "multi_flow":       False,  # cannot have multiple flows

            # Commerce
            "products":         True,
            "orders":           True,
            "order_tracking":   True,
            "storefront":       True,
            "inventory":        True,

            # CRM
            "crm":              False,
            "customer_memory":  True,   # basic — name + address
            "customer_segments":False,

            # Broadcast
            "broadcast":        False,

            # Analytics
            "analytics_basic":  True,
            "analytics_advanced":False,

            # AI
            "ai_assistant":     True,
            "ai_faq_kb":        False,  # custom FAQ knowledge base

            # Support layer (universal — always available)
            "support_layer":    True,
            "human_handoff":    True,

            # Premium
            "voice_notes":      False,
            "white_label":      False,
            "multi_user":       False,
            "api_access":       False,

            # Limits
            "max_products":     50,
            "max_customers":    500,
            "max_broadcasts_mo": 0,
            "max_orders_mo":    200,
        }
    },

    "growth": {
        "name":         "Growth",
        "price_ngn":    35000,
        "description":  "CRM, broadcasts, analytics",
        "features": {
            "commerce":          True,
            "booking":           True,
            "lead_gen":          True,
            "support_template":  True,
            "multi_flow":        False,

            "products":          True,
            "orders":            True,
            "order_tracking":    True,
            "storefront":        True,
            "inventory":         True,

            "crm":               True,
            "customer_memory":   True,
            "customer_segments": False,

            "broadcast":         True,

            "analytics_basic":   True,
            "analytics_advanced":False,

            "ai_assistant":      True,
            "ai_faq_kb":         False,

            "support_layer":     True,
            "human_handoff":     True,

            "voice_notes":       False,
            "white_label":       False,
            "multi_user":        False,
            "api_access":        False,

            "max_products":      200,
            "max_customers":     2000,
            "max_broadcasts_mo": 4,
            "max_orders_mo":     1000,
        }
    },

    "premium": {
        "name":         "Premium",
        "price_ngn":    75000,
        "description":  "AI FAQ, voice notes, advanced analytics",
        "features": {
            "commerce":          True,
            "booking":           True,
            "lead_gen":          True,
            "support_template":  True,
            "multi_flow":        True,

            "products":          True,
            "orders":            True,
            "order_tracking":    True,
            "storefront":        True,
            "inventory":         True,

            "crm":               True,
            "customer_memory":   True,
            "customer_segments": True,

            "broadcast":         True,

            "analytics_basic":   True,
            "analytics_advanced":True,

            "ai_assistant":      True,
            "ai_faq_kb":         True,

            "support_layer":     True,
            "human_handoff":     True,

            "voice_notes":       True,
            "white_label":       False,
            "multi_user":        False,
            "api_access":        True,

            "max_products":      -1,     # unlimited
            "max_customers":     -1,
            "max_broadcasts_mo": -1,
            "max_orders_mo":     -1,
        }
    },

    "enterprise": {
        "name":         "Enterprise",
        "price_ngn":    -1,             # custom pricing
        "description":  "White label, multi-user, priority support",
        "features": {
            "commerce":          True,
            "booking":           True,
            "lead_gen":          True,
            "support_template":  True,
            "multi_flow":        True,

            "products":          True,
            "orders":            True,
            "order_tracking":    True,
            "storefront":        True,
            "inventory":         True,

            "crm":               True,
            "customer_memory":   True,
            "customer_segments": True,

            "broadcast":         True,

            "analytics_basic":   True,
            "analytics_advanced":True,

            "ai_assistant":      True,
            "ai_faq_kb":         True,

            "support_layer":     True,
            "human_handoff":     True,

            "voice_notes":       True,
            "white_label":       True,
            "multi_user":        True,
            "api_access":        True,

            "max_products":      -1,
            "max_customers":     -1,
            "max_broadcasts_mo": -1,
            "max_orders_mo":     -1,
        }
    },

    # Internal plan for CodedLabs own testing — all features
    "internal": {
        "name":     "Internal",
        "price_ngn": 0,
        "description": "CodedLabs internal use",
        "features": {k: True for k in [
            "commerce","booking","lead_gen","support_template","multi_flow",
            "products","orders","order_tracking","storefront","inventory",
            "crm","customer_memory","customer_segments","broadcast",
            "analytics_basic","analytics_advanced","ai_assistant","ai_faq_kb",
            "support_layer","human_handoff","voice_notes","white_label",
            "multi_user","api_access",
        ]} | {
            "max_products": -1, "max_customers": -1,
            "max_broadcasts_mo": -1, "max_orders_mo": -1,
        }
    },
}

DEFAULT_PLAN = "starter"


# ─────────────────────────────────────────────────────
# FEATURE CHECK  (use this everywhere, never raw strings)
# ─────────────────────────────────────────────────────

def can(client: dict, feature: str) -> bool:
    """
    Returns True if this client's plan allows the feature.
    Checks in order: feature_flags override → plan features.
    """
    plan_name = client.get("plan", DEFAULT_PLAN) or DEFAULT_PLAN
    plan      = PLANS.get(plan_name, PLANS[DEFAULT_PLAN])
    base      = plan["features"].get(feature, False)

    # Per-client feature flag overrides (set by CodedLabs admin)
    flags = client.get("feature_flags") or {}
    if isinstance(flags, str):
        import json
        try:
            flags = json.loads(flags)
        except Exception:
            flags = {}

    if feature in flags:
        return bool(flags[feature])

    return bool(base)


def limit(client: dict, limit_key: str) -> int:
    """
    Returns the numeric limit for a feature (-1 = unlimited).
    limit_key examples: max_products, max_customers, max_broadcasts_mo
    """
    plan_name = client.get("plan", DEFAULT_PLAN) or DEFAULT_PLAN
    plan      = PLANS.get(plan_name, PLANS[DEFAULT_PLAN])
    base      = plan["features"].get(limit_key, 0)

    flags = client.get("feature_flags") or {}
    if isinstance(flags, str):
        import json
        try:
            flags = json.loads(flags)
        except Exception:
            flags = {}

    if limit_key in flags:
        return int(flags[limit_key])

    return int(base)


def is_within_limit(client: dict, limit_key: str, current_count: int) -> bool:
    """Returns True if current_count is within the plan limit."""
    cap = limit(client, limit_key)
    if cap == -1:
        return True     # unlimited
    return current_count < cap


def get_plan(client: dict) -> dict:
    """Return full plan dict for a client."""
    plan_name = client.get("plan", DEFAULT_PLAN) or DEFAULT_PLAN
    return PLANS.get(plan_name, PLANS[DEFAULT_PLAN])


def upgrade_message(client: dict, feature: str) -> str:
    """Return a user-friendly upgrade prompt for a locked feature."""
    plan      = get_plan(client)
    plan_name = plan["name"]
    msgs = {
        "broadcast":         f"📣 Broadcasts are available on the Growth plan and above. You're currently on {plan_name}.",
        "crm":               f"👥 CRM features are available on the Growth plan and above.",
        "analytics_advanced":f"📊 Advanced analytics are available on the Premium plan.",
        "ai_faq_kb":         f"🧠 AI knowledge base is available on the Premium plan.",
        "voice_notes":       f"🎙️ Voice note ordering is available on the Premium plan.",
        "multi_flow":        f"🔀 Running multiple flows is available on the Premium plan.",
        "white_label":       f"🏷️ White labelling is available on the Enterprise plan.",
    }
    return msgs.get(feature,
        f"This feature is not available on the {plan_name} plan. "
        f"Contact CodedLabs to upgrade."
    )
