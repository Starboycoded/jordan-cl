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
    return (req.args.get("secret") == ADMIN_SECRET or
            req.headers.get("X-Admin-Secret") == ADMIN_SECRET)


# ─────────────────────────────────────────────────────
# MAIN DASHBOARD PAGE
# ─────────────────────────────────────────────────────

@dashboard.route("/dashboard/<slug>")
def product_dashboard(slug: str):
    if not _auth(request):
        return _unauth()

    client = db_layer.get_client_by_slug(slug)
    if not client:
        return "Store not found.", 404

    t_cfg    = get_template(client.get("template", "general"))
    cats     = t_cfg.get("categories", [])
    currency = client.get("currency", "NGN")
    secret   = ADMIN_SECRET

    return render_template("dashboard.html",
        client     = client,
        slug       = slug,
        secret     = secret,
        currency   = currency,
        primary    = t_cfg.get("primary", "#25D366"),
        categories = cats,
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
