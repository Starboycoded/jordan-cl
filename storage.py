# ══════════════════════════════════════════════════════
# JORDAN v5.1 — SUPABASE STORAGE (Image Uploads)
# ══════════════════════════════════════════════════════

import os
import uuid
import logging
import mimetypes
from database import db

logger = logging.getLogger(__name__)

STORAGE_BUCKET = "product-images"   # Create this bucket in Supabase Storage


def upload_product_image(file_bytes: bytes, filename: str, client_slug: str) -> str | None:
    """
    Upload a product image to Supabase Storage.
    Returns the public URL or None on failure.
    
    Path structure: {client_slug}/{uuid}.{ext}
    """
    try:
        ext      = _safe_extension(filename)
        key      = f"{client_slug}/{uuid.uuid4().hex}.{ext}"
        mimetype = mimetypes.guess_type(filename)[0] or "image/jpeg"

        db().storage.from_(STORAGE_BUCKET).upload(
            path         = key,
            file         = file_bytes,
            file_options = {"content-type": mimetype, "upsert": "true"}
        )

        # Get public URL
        result = db().storage.from_(STORAGE_BUCKET).get_public_url(key)
        return result

    except Exception as e:
        logger.error(f"[Storage] upload_product_image: {e}")
        return None


def delete_product_image(image_url: str) -> bool:
    """Delete image from Supabase Storage given its public URL."""
    try:
        # Extract path from URL
        # URL format: https://xxx.supabase.co/storage/v1/object/public/product-images/{path}
        marker = f"/object/public/{STORAGE_BUCKET}/"
        if marker not in image_url:
            return False
        path = image_url.split(marker)[-1]
        db().storage.from_(STORAGE_BUCKET).remove([path])
        return True
    except Exception as e:
        logger.error(f"[Storage] delete_product_image: {e}")
        return False


def _safe_extension(filename: str) -> str:
    """Extract and validate file extension."""
    allowed = {"jpg", "jpeg", "png", "webp", "gif"}
    parts   = filename.rsplit(".", 1)
    if len(parts) == 2 and parts[1].lower() in allowed:
        return parts[1].lower()
    return "jpg"


# ── Supabase Storage Setup Instructions ───────────────
# 1. Go to Supabase Dashboard → Storage
# 2. Create a new bucket named: product-images
# 3. Set it to PUBLIC (so images are accessible without auth)
# 4. Add this policy for uploads (service role bypasses RLS anyway):
#
#    Policy name: Allow uploads
#    Operation: INSERT
#    Target roles: service_role
#    Policy: true
