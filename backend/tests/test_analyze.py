"""Test /api/analyze with stubbed AI models so it runs without downloading weights."""
import io
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image


def make_photo_bytes():
    """Return bytes of a tiny valid JPEG photo."""
    img = Image.new("RGB", (10, 10), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        import main
        self.client = TestClient(main.app)

    def _post_photo(self, extra=None, debug=False):
        data = {"lat": "12.9716", "lng": "77.5946", "address": "Bengaluru"}
        if debug:
            data["debug"] = "true"
        if extra:
            data.update(extra)
        files = {"file": ("photo.jpg", io.BytesIO(make_photo_bytes()), "image/jpeg")}
        return self.client.post("/api/analyze", data=data, files=files)

    @mock.patch("main.YOLO_AVAILABLE", False)
    @mock.patch("main.world_model", None)
    @mock.patch("main.detect_materials")
    def test_analyze_returns_5_values(self, mock_detect):
        """detect_materials must return 5 values: dets, model, others, is_site, verification."""
        mock_detect.return_value = ([], "visual", [], False,
                                    {"checked": 0, "rejected": 0, "kept": 0})
        r = self._post_photo()
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertIn("model", j)
        self.assertEqual(j["model"], "visual")
        self.assertIn("detections", j)
        self.assertIn("non_construction", j)
        self.assertIn("is_construction_site", j)
        self.assertEqual(j["verification"]["checked"], 0)

    @mock.patch("main.YOLO_AVAILABLE", False)
    @mock.patch("main.world_model", None)
    @mock.patch("main.detect_materials")
    def test_analyze_debug_includes_last_debug(self, mock_detect):
        """?debug=1 should include the _last_debug dict in the response."""
        mock_detect.return_value = ([], "visual", [], False,
                                    {"checked": 0, "rejected": 0, "kept": 0})
        import main
        main._last_debug = {"world_raw": [], "coco_raw": [], "clip_frame_p": 0.9}
        r = self._post_photo(debug=True)
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertIn("debug", j)
        self.assertEqual(j["debug"]["clip_frame_p"], 0.9)

    @mock.patch("main.YOLO_AVAILABLE", False)
    @mock.patch("main.world_model", None)
    @mock.patch("main.detect_materials")
    def test_rejected_photo_has_model_field(self, mock_detect):
        """Oversized photo rejection must still include a model field."""
        files = {"file": ("photo.jpg", io.BytesIO(b"x" * (30 * 1024 * 1024)), "image/jpeg")}
        data = {"lat": "12.9716", "lng": "77.5946", "address": "Bengaluru"}
        r = self.client.post("/api/analyze", data=data, files=files)
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertIn("model", j)
        self.assertEqual(j["model"], "rejected")

    @mock.patch("main.YOLO_AVAILABLE", False)
    @mock.patch("main.world_model", None)
    @mock.patch("main.detect_materials")
    def test_invalid_image_has_model_field(self, mock_detect):
        """Non-image upload rejection must still include a model field."""
        files = {"file": ("photo.jpg", io.BytesIO(b"not an image"), "image/jpeg")}
        data = {"lat": "12.9716", "lng": "77.5946", "address": "Bengaluru"}
        r = self.client.post("/api/analyze", data=data, files=files)
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertIn("model", j)
        self.assertEqual(j["model"], "rejected")


if __name__ == "__main__":
    unittest.main()
