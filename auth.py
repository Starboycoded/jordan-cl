# ══════════════════════════════════════════════════════
# JORDAN v5.4 — AUTHENTICATION
# Session-based login for merchant dashboards.
# No more ?secret= in URLs after first login.
# ══════════════════════════════════════════════════════

import os
import logging
from functools import wraps
from flask import (Blueprint, request, render_template, redirect,
                   url_for, session as flask_session, jsonify)
import database as db_layer

logger       = logging.getLogger(__name__)
auth         = Blueprint("auth", __name__)
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "CodedLabs2025")


def login_required(f):
    """Redirect to /login if not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not flask_session.get("logged_in"):
            return redirect(f"/login?next={request.url}")
        return f(*args, **kwargs)
    return decorated


def get_current_client() -> dict | None:
    slug = flask_session.get("slug")
    if not slug:
        return None
    return db_layer.get_client_by_slug(slug)


def is_platform_admin() -> bool:
    return flask_session.get("is_admin", False)


@auth.route("/login", methods=["GET", "POST"])
def login():
    if flask_session.get("logged_in"):
        if flask_session.get("is_admin"):
            return redirect("/codedlabs")
        return redirect(f"/dashboard/{flask_session.get('slug', '')}")

    error = None

    if request.method == "POST":
        slug   = (request.form.get("slug") or "").strip().lower()
        secret = (request.form.get("secret") or "").strip()

        # Platform admin (any slug)
        if secret == ADMIN_SECRET:
            flask_session.permanent  = True
            flask_session["logged_in"] = True
            flask_session["is_admin"]  = True
            flask_session["slug"]      = slug or "admin"
            next_url = request.args.get("next", "/codedlabs")
            return redirect(next_url)

        # Per-client login
        if not slug:
            error = "Enter your Store ID."
        else:
            client = db_layer.get_client_by_slug(slug)
            if not client:
                error = f"Store '{slug}' not found."
            elif not client.get("active"):
                error = "This store is suspended. Contact CodedLabs."
            else:
                client_secret = client.get("admin_secret") or ADMIN_SECRET
                if secret == client_secret:
                    flask_session.permanent    = True
                    flask_session["logged_in"] = True
                    flask_session["is_admin"]  = False
                    flask_session["slug"]      = slug
                    flask_session["client_id"] = str(client["id"])
                    flask_session["biz_name"]  = client.get("business_name", slug)
                    next_url = request.args.get("next", f"/dashboard/{slug}")
                    return redirect(next_url)
                else:
                    error = "Incorrect secret."

    return render_template("login.html", error=error)


@auth.route("/logout")
def logout():
    flask_session.clear()
    return redirect("/login")


@auth.route("/auth/status")
def auth_status():
    return jsonify({
        "logged_in": flask_session.get("logged_in", False),
        "slug":      flask_session.get("slug"),
        "is_admin":  flask_session.get("is_admin", False),
    })
