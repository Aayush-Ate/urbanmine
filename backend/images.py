"""Shrinking uploaded photos before they are stored.

Every photo is kept twice: a small thumbnail for lists, and one bounded
full copy that only the viewer loads. Same idea as YouTube — cheap image
in the feed, the real one on demand.

Clients already downscale before upload, but the API can be called
directly, so the cap lives here too.
"""
import io

from PIL import Image, ImageOps

FULL_MAX = 1600
THUMB_MAX = 480


def photo_jpeg(raw, max_side=FULL_MAX, quality=82):
    """Re-encode any accepted image as a bounded JPEG. Never upscales."""
    img = Image.open(io.BytesIO(raw))
    # phones store rotation in EXIF; the pixels must be turned first
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        # flatten transparency onto white instead of letting it turn black
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()
