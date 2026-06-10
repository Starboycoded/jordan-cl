# ══════════════════════════════════════════════════════
# JORDAN v5.1 — PRODUCT MANAGEMENT DASHBOARD
# /dashboard/{slug} → full product CRUD + image upload
# ══════════════════════════════════════════════════════

import os
import json
import base64
import logging
import mimetypes
from flask import Blueprint, request, jsonify, abort, render_template
import database as db_layer
import storage as store
from templates_config import get_template

logger   = logging.getLogger(__name__)
dashboard = Blueprint("dashboard", __name__)

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "CodedLabs2025")
CATALOG_BASE = os.environ.get("CATALOG_BASE_URL", "https://bot-test-wddr.onrender.com/shop")


def _auth(req) -> bool:
    # Accept: URL param, header, or active Flask session
    from flask import session as flask_session
    if flask_session.get("logged_in"):
        return True
    return (req.args.get("secret") == ADMIN_SECRET or
            req.headers.get("X-Admin-Secret") == ADMIN_SECRET)


# ─────────────────────────────────────────────────────
# MAIN DASHBOARD PAGE
# ─────────────────────────────────────────────────────

@dashboard.route("/dashboard/<slug>")
@dashboard.route("/admin/<slug>")
def product_dashboard(slug: str):
    if not _auth(request):
        return _unauth()

    client = db_layer.get_client_by_slug(slug)
    if not client:
        return "Store not found.", 404

    from modules import get_enabled_modules
    from subscriptions import get_plan

    t_cfg    = get_template(client.get("template", "general"))
    currency = client.get("currency", "NGN")
    secret   = ADMIN_SECRET
    modules  = get_enabled_modules(client)
    plan     = get_plan(client).get("name", "Starter")

    # Load data for each enabled module
    analytics    = db_layer.get_analytics(str(client["id"]))
    products     = db_layer.get_products(str(client["id"])) if modules.get("commerce") else []
    orders       = db_layer.get_orders(str(client["id"]), limit=100) if modules.get("commerce") else []
    appointments = db_layer.get_appointments(str(client["id"]), limit=50) if modules.get("booking") else []
    leads        = db_layer.get_leads(str(client["id"]), limit=100) if modules.get("leadgen") else []
    faqs         = db_layer.get_faqs(str(client["id"])) if modules.get("support") else []

    status_colors = {
        "pending": "#f59e0b", "confirmed": "#3b82f6",
        "awaiting_payment": "#a78bfa", "paid": "#06b6d4",
        "processing": "#f97316", "delivered": "#22c55e", "cancelled": "#ef4444",
    }

    return render_template("dashboard.html",
        client        = client,
        slug          = slug,
        secret        = secret,
        currency      = currency,
        primary       = t_cfg.get("primary", "#25D366"),
        modules       = modules,
        plan          = plan,
        products      = products,
        orders        = orders,
        appointments  = appointments,
        leads         = leads,
        faqs          = faqs,
        stats         = analytics,
        low_stock     = analytics.get("low_stock", []),
        status_colors = status_colors,
    )


@dashboard.route("/api/<slug>/upload-image", methods=["POST"])
def upload_image(slug: str):
    if not _auth(request):
        return jsonify({"error": "Unauthorized"}), 403

    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    if "image" not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    file     = request.files["image"]
    filename = file.filename or "upload.jpg"

    # Validate mimetype — fall back to filename extension if browser sends wrong type
    allowed_mimes = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
    mime = file.mimetype or mimetypes.guess_type(filename)[0] or ""
    if mime not in allowed_mimes:
        # Last resort — check extension directly
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
            return jsonify({"error": f"Invalid file type '{mime}'. Use JPG, PNG, or WebP."}), 400

    file_bytes = file.read()
    if len(file_bytes) > 5 * 1024 * 1024:
        return jsonify({"error": "File too large. Max 5MB."}), 400

    url, err = store.upload_product_image(file_bytes, filename, slug)
    if err:
        logger.error(f"[Dashboard] Image upload error for {slug}: {err}")
        return jsonify({"error": err}), 500
    if not url:
        return jsonify({"error": "Upload failed: no URL returned"}), 500

    logger.info(f"[Dashboard] Image uploaded for {slug}: {url}")
    return jsonify({"url": url})


# ─────────────────────────────────────────────────────
# SETTINGS PAGE
# ─────────────────────────────────────────────────────

@dashboard.route("/dashboard/<slug>/settings")
def settings_page(slug: str):
    if not _auth(request):
        return _unauth()

    client = db_layer.get_client_by_slug(slug)
    if not client:
        return "Store not found.", 404

    secret     = ADMIN_SECRET
    currencies = ["NGN","GHS","KES","ZAR","USD","GBP","EUR","BRL","INR","IDR"]

    from templates_config import get_business_types
    business_types = get_business_types()

    return render_template("settings.html",
        client         = client,
        slug           = slug,
        secret         = secret,
        currencies     = currencies,
        business_types = business_types,
    )


@dashboard.route("/api/<slug>", methods=["PUT"])
def api_update_client_settings(slug: str):
    if not _auth(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    body    = request.json or {}
    allowed = {"business_name", "greeting", "template", "currency",
               "phone_number_id", "wa_token", "whatsapp_number", "merchant_phone", "ai_model", "active"}
    updates = {k: v for k, v in body.items() if k in allowed}
    ok      = db_layer.update_client(str(client["id"]), updates)
    return jsonify({"success": ok})


# ─────────────────────────────────────────────────────
# APPOINTMENTS API
# ─────────────────────────────────────────────────────

@dashboard.route("/api/<slug>/appointments/<ref>/status", methods=["PUT"])
def update_appointment_status(slug: str, ref: str):
    if not _auth(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    body   = request.json or {}
    status = body.get("status", "")
    valid  = {"pending", "confirmed", "completed", "cancelled", "no_show"}
    if status not in valid:
        return jsonify({"error": f"Status must be one of: {valid}"}), 400

    ok = db_layer.update_appointment_status(ref, str(client["id"]), status)
    if ok:
        from merchant import notify_appointment_status_to_customer
        import threading
        threading.Thread(
            target=notify_appointment_status_to_customer,
            args=(ref, status, client), daemon=True
        ).start()
    return jsonify({"success": ok})


# ─────────────────────────────────────────────────────
# LEADS API
# ─────────────────────────────────────────────────────

@dashboard.route("/api/<slug>/leads/<ref>/status", methods=["PUT"])
def update_lead_status(slug: str, ref: str):
    if not _auth(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    body   = request.json or {}
    status = body.get("status", "")
    valid  = {"new", "contacted", "qualified", "converted", "lost"}
    if status not in valid:
        return jsonify({"error": f"Status must be one of: {valid}"}), 400

    ok = db_layer.update_lead_status(ref, str(client["id"]), status)
    return jsonify({"success": ok})


# ─────────────────────────────────────────────────────
# FAQS API
# ─────────────────────────────────────────────────────

@dashboard.route("/api/<slug>/faqs", methods=["POST"])
def create_faq(slug: str):
    if not _auth(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    body = request.json or {}
    if not body.get("question") or not body.get("answer"):
        return jsonify({"error": "question and answer required"}), 400

    faq = db_layer.create_faq(
        client_id  = str(client["id"]),
        question   = body["question"],
        answer     = body["answer"],
        sort_order = body.get("sort_order", 0)
    )
    return jsonify({"success": bool(faq), "faq": faq}), 201


@dashboard.route("/api/<slug>/faqs/<int:faq_id>", methods=["PUT"])
def update_faq(slug: str, faq_id: int):
    if not _auth(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    body    = request.json or {}
    allowed = {"question", "answer", "sort_order", "active"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields"}), 400

    ok = db_layer.update_faq(faq_id, str(client["id"]), updates)
    return jsonify({"success": ok})


@dashboard.route("/api/<slug>/faqs/<int:faq_id>", methods=["DELETE"])
def delete_faq(slug: str, faq_id: int):
    if not _auth(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    ok = db_layer.delete_faq(faq_id, str(client["id"]))
    return jsonify({"success": ok})
