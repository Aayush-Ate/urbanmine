"""Tests for images.py. Plain Pillow, no models, no files."""
import io
import unittest

from PIL import Image

from images import THUMB_MAX, photo_jpeg


def photo_bytes(size=(2000, 1500), mode="RGB"):
    buf = io.BytesIO()
    # RGBA here is fully transparent, so the flatten really has work to do
    Image.new(mode, size, (120, 90, 60, 0) if mode == "RGBA" else (120, 90, 60)).save(
        buf, "PNG" if mode == "RGBA" else "JPEG"
    )
    return buf.getvalue()


class TestPhotoJpeg(unittest.TestCase):
    def test_full_copy_is_capped_and_jpeg(self):
        img = Image.open(io.BytesIO(photo_jpeg(photo_bytes())))
        self.assertEqual(img.format, "JPEG")
        self.assertLessEqual(max(img.size), 1600)

    def test_thumbnail_is_smaller_than_full(self):
        full = photo_jpeg(photo_bytes())
        thumb = photo_jpeg(full, THUMB_MAX, 72)
        self.assertLess(len(thumb), len(full))
        self.assertLessEqual(max(Image.open(io.BytesIO(thumb)).size), THUMB_MAX)

    def test_small_photo_is_not_upscaled(self):
        img = Image.open(io.BytesIO(photo_jpeg(photo_bytes(size=(10, 10)))))
        self.assertEqual(img.size, (10, 10))

    def test_transparent_png_lands_on_white_not_black(self):
        img = Image.open(io.BytesIO(photo_jpeg(photo_bytes(mode="RGBA"))))
        r, g, b = img.convert("RGB").getpixel((0, 0))
        self.assertGreater(r + g + b, 600)


if __name__ == "__main__":
    unittest.main()
