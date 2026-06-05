# ══════════════════════════════════════════════════════
# JORDAN v5.3 — SUPABASE STORAGE (Image Uploads)
# Audited and hardened. Full error chain logging.
# Every failure point is explicit.
# ══════════════════════════════════════════════════════

import os
import uuid
import logging
import mimetypes

logger         = logging.getLogger(__name__)
STORAGE_BUCKET = "product-images"

ALLOWED_MIMES = {
    "image/jpeg": "jpg",
    "image/jpg":  "jpg",
    "image/png":  "png",
    "image/webp": "webp",
    "image/gif":  "gif",
}
MAX_FILE_SIZE = 5 * 1024 * 1024   # 5 MB


def upload_product_image(file_bytes: bytes, filename: str,
                         client_slug: str) -> tuple[str | None, str | None]:
    """
    Upload a product image to Supabase Storage.

    Returns:
        (public_url, None)   on success
        (None, error_msg)    on failure

    Never raises — all errors are caught and returned as messages.
    """
    # ── 1. Validate input ───────────────────────────
    if not file_bytes:
        return None, "File is empty."

    if len(file_bytes) > MAX_FILE_SIZE:
        mb = len(file_bytes) / (1024 * 1024)
        return None, f"File too large ({mb:.1f} MB). Maximum is 5 MB."

    if not filename:
        filename = "upload.jpg"

    # ── 2. Determine MIME type ───────────────────────
    mime = mimetypes.guess_type(filename)[0] or "image/jpeg"
    if mime not in ALLOWED_MIMES:
        return None, f"File type '{mime}' not allowed. Use JPG, PNG, or WebP."

    ext = ALLOWED_MIMES[mime]
    key = f"{client_slug}/{uuid.uuid4().hex}.{ext}"

    # ── 3. Get Supabase client ───────────────────────
    try:
        from database import db
        supabase = db()
    except Exception as e:
        logger.error(f"[Storage] Failed to get Supabase client: {e}")
        return None, "Database connection failed. Please try again."

    # ── 4. Upload to Supabase Storage ───────────────
    try:
        supabase.storage.from_(STORAGE_BUCKET).upload(
            path         = key,
            file         = file_bytes,
            file_options = {
                "content-type": mime,
                "upsert":       "true",
                "cache-control": "3600",
            }
        )
        logger.info(f"[Storage] Uploaded: {key} ({len(file_bytes)} bytes)")
    except Exception as e:
        err = str(e)
        logger.error(f"[Storage] Upload failed for {key}: {err}")

        # Diagnose common failures
        if "bucket" in err.lower() or "not found" in err.lower():
            return None, (
                "Storage bucket 'product-images' not found. "
                "Create it in Supabase → Storage and set it to Public."
            )
        if "policy" in err.lower() or "unauthorized" in err.lower():
            return None, (
                "Storage permission denied. "
                "Make sure you're using the service_role key, not the anon key."
            )
        return None, f"Upload failed: {err[:200]}"

    # ── 5. Get public URL ────────────────────────────
    try:
        public_url = supabase.storage.from_(STORAGE_BUCKET).get_public_url(key)
        if not public_url:
            raise ValueError("Empty URL returned")
        logger.info(f"[Storage] Public URL: {public_url}")
    except Exception as e:
        logger.error(f"[Storage] get_public_url failed for {key}: {e}")
        return None, "Upload succeeded but failed to generate public URL. Check Supabase Storage settings."

    # ── 6. Verify URL looks valid ────────────────────
    if not public_url.startswith("http"):
        logger.error(f"[Storage] Invalid URL format: {public_url}")
        return None, f"Unexpected URL format returned: {public_url[:100]}"

    return public_url, None


def delete_product_image(image_url: str) -> tuple[bool, str | None]:
    """
    Delete image from Supabase Storage by its public URL.
    Returns (True, None) on success, (False, error_msg) on failure.
    """
    if not image_url:
        return False, "No URL provided."

    marker = f"/object/public/{STORAGE_BUCKET}/"
    if marker not in image_url:
        return False, f"URL does not belong to bucket '{STORAGE_BUCKET}'."

    path = image_url.split(marker)[-1].split("?")[0]  # strip query params

    try:
        from database import db
        db().storage.from_(STORAGE_BUCKET).remove([path])
        logger.info(f"[Storage] Deleted: {path}")
        return True, None
    except Exception as e:
        logger.error(f"[Storage] Delete failed for {path}: {e}")
        return False, str(e)


def verify_bucket_exists() -> tuple[bool, str]:
    """
    Check that the product-images bucket exists and is accessible.
    Call this from the health check endpoint.
    Returns (True, "ok") or (False, error_message).
    """
    try:
        from database import db
        buckets = db().storage.list_buckets()
        names   = [b.name for b in buckets]
        if STORAGE_BUCKET in names:
            return True, "ok"
        return False, (
            f"Bucket '{STORAGE_BUCKET}' not found. "
            f"Existing buckets: {names}"
        )
    except Exception as e:
        return False, str(e)
