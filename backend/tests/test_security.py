"""The rules the security pass added, pinned so they cannot quietly regress.

These are the cheap checks: what the API accepts, what it refuses, and what a
caller is allowed to make it do with a path. Auth and a shared rate limit are
not here because they are not built — docs/SECURITY.md says so plainly.
"""
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

from app.core.ratelimit import SlidingWindow
from app.storage import store


def photo():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(10, 120, 60)).save(buf, format="JPEG")
    return buf.getvalue()


class TestListingValidation(unittest.TestCase):
    def setUp(self):
        from app import main
        self.client = TestClient(main.app)
        self.tmp = tempfile.TemporaryDirectory()
        self.real_data_file = store.DATA_FILE
        store.DATA_FILE = Path(self.tmp.name) / "data.json"

    def tearDown(self):
        store.DATA_FILE = self.real_data_file
        self.tmp.cleanup()

    def test_photo_url_outside_uploads_is_dropped(self):
        # DELETE takes the last path segment of this string and unlinks it
        r = self.client.post("/api/listings", json={
            "material": "Wood", "quantity": 10,
            "image_url": "/uploads/../../../etc/passwd",
            "thumb_url": "https://example.com/tracker.gif",
        })
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["image_url"])
        self.assertIsNone(r.json()["thumb_url"])

    def test_our_own_upload_url_is_kept(self):
        r = self.client.post("/api/listings", json={
            "material": "Wood", "quantity": 10, "image_url": "/uploads/a1b2c3d4e5.jpg",
        })
        self.assertEqual(r.json()["image_url"], "/uploads/a1b2c3d4e5.jpg")

    def test_negative_quantity_is_refused(self):
        r = self.client.post("/api/listings", json={"material": "Wood", "quantity": -5})
        self.assertEqual(r.status_code, 422)

    def test_unknown_condition_is_refused(self):
        r = self.client.post("/api/listings",
                             json={"material": "Wood", "quantity": 5,
                                   "condition": "Mint"})
        self.assertEqual(r.status_code, 422)

    def test_out_of_range_coordinates_are_refused(self):
        r = self.client.post("/api/listings",
                             json={"material": "Wood", "quantity": 5,
                                   "lat": 500, "lng": 77.6})
        self.assertEqual(r.status_code, 422)

    def test_box_outside_the_frame_becomes_no_box(self):
        r = self.client.post("/api/listings",
                             json={"material": "Wood", "quantity": 5,
                                   "bbox": [0.5, 0.5, 0.2, 0.9]})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["bbox"])

    def test_unknown_request_status_is_refused(self):
        listing = self.client.post("/api/listings",
                                   json={"material": "Wood", "quantity": 5}).json()
        req = self.client.post("/api/requests", json={
            "listing_id": listing["id"], "buyer_name": "A",
        }).json()
        r = self.client.patch(f"/api/requests/{req['id']}", json={"status": "deleted"})
        self.assertEqual(r.status_code, 422)


class TestAnalyzeHardening(unittest.TestCase):
    def setUp(self):
        from app import main
        self.client = TestClient(main.app)

    def test_non_image_content_type_is_refused_before_reading(self):
        r = self.client.post(
            "/api/analyze",
            files={"file": ("x.pdf", io.BytesIO(b"%PDF-1.7"), "application/pdf")},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["model"], "rejected")
        self.assertIn("JPG", r.json()["error"])

    @mock.patch("app.main.detect_materials")
    def test_oversized_body_is_cut_before_analysis(self, detect):
        with mock.patch("app.main.MAX_UPLOAD_BYTES", 1024):
            r = self.client.post(
                "/api/analyze",
                files={"file": ("photo.jpg", io.BytesIO(b"x" * 5000), "image/jpeg")},
            )
        self.assertEqual(r.json()["model"], "rejected")
        detect.assert_not_called()

    def test_rate_limit_returns_429(self):
        from app import main
        with mock.patch.object(main, "ANALYZE_LIMIT", SlidingWindow(1, 60)):
            first = self.client.post(
                "/api/analyze",
                files={"file": ("p.jpg", io.BytesIO(b"no"), "image/jpeg")},
            )
            second = self.client.post(
                "/api/analyze",
                files={"file": ("p.jpg", io.BytesIO(b"no"), "image/jpeg")},
            )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)


class TestHeadersAndCors(unittest.TestCase):
    def setUp(self):
        from app import main
        self.client = TestClient(main.app)

    def test_security_headers_are_present(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertEqual(r.headers["x-frame-options"], "DENY")
        self.assertEqual(r.headers["referrer-policy"], "no-referrer")

    def test_cors_does_not_allow_credentials_with_a_wildcard(self):
        r = self.client.get("/api/health", headers={"Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-credentials", r.headers)


class TestPathGuard(unittest.TestCase):
    def test_delete_image_refuses_a_traversal_name(self):
        # the schema already blocks this string; this is the second lock, in
        # the function that touches the filesystem
        with tempfile.TemporaryDirectory() as tmp:
            real_dir = store.UPLOAD_DIR
            store.UPLOAD_DIR = Path(tmp)
            try:
                victim = Path(tmp).parent / "do-not-delete.txt"
                victim.write_text("x")
                store.delete_image(f"../{victim.name}")
                self.assertTrue(victim.exists())
            finally:
                store.UPLOAD_DIR = real_dir


class TestLimiter(unittest.TestCase):
    def test_allows_up_to_the_limit_then_blocks(self):
        limiter = SlidingWindow(2, 60)
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("a"))
        self.assertFalse(limiter.allow("a"))
        # a different client has its own budget
        self.assertTrue(limiter.allow("b"))


if __name__ == "__main__":
    unittest.main()
