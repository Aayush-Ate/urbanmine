"""The hosted vision provider, tested without a network or a key.

The point of these tests is the part that can go wrong quietly: a model reply
with an unknown material, an absurd quantity, or a box outside the frame. Those
must become a clean detection list, never a wrong listing.
"""
import os
import unittest
from unittest import mock

from app.ai import vlm


class TestParsing(unittest.TestCase):
    def test_known_material_becomes_a_detection(self):
        out = vlm._shape({
            "is_construction_site": True,
            "materials": [{
                "material": "Bricks", "quantity": 1200, "condition": "Good",
                "confidence": 0.82, "bbox": [0.1, 0.2, 0.6, 0.7], "note": "stack by gate",
            }],
        })
        det = out["dets"][0]
        self.assertEqual(det["material"], "Bricks")
        self.assertEqual(det["unit"], "pcs")
        self.assertEqual(det["bbox"], [0.1, 0.2, 0.6, 0.7])
        # Good pays 85% of the ₹6 base
        self.assertEqual(det["suggested_price_per_unit"], 5)
        self.assertEqual(out["verification"]["kept"], 1)
        self.assertTrue(out["is_site"])

    def test_unknown_material_is_dropped(self):
        out = vlm._shape({"is_construction_site": True,
                          "materials": [{"material": "Uranium", "quantity": 5}]})
        self.assertEqual(out["dets"], [])
        self.assertFalse(out["is_site"])

    def test_singular_word_is_mapped(self):
        out = vlm._shape({"is_construction_site": True,
                          "materials": [{"material": "timber", "quantity": 200}]})
        self.assertEqual(out["dets"][0]["material"], "Wood")

    def test_absurd_quantity_is_clamped_to_a_full_frame(self):
        out = vlm._shape({"is_construction_site": True,
                          "materials": [{"material": "Marble", "quantity": 90000}]})
        self.assertLessEqual(out["dets"][0]["quantity"], 400)

    def test_box_outside_the_frame_is_dropped(self):
        out = vlm._shape({"is_construction_site": True,
                          "materials": [{"material": "Metal", "quantity": 90,
                                         "bbox": [-0.2, 0.1, 1.4, 0.6]}]})
        self.assertIsNone(out["dets"][0]["bbox"])

    def test_inverted_box_is_dropped(self):
        self.assertIsNone(vlm._bbox([0.8, 0.8, 0.2, 0.2]))

    def test_household_answer_has_no_site(self):
        out = vlm._shape({
            "is_construction_site": False,
            "materials": [],
            "not_construction": [{"label": "bedsheet", "confidence": 0.9}],
        })
        self.assertEqual(out["dets"], [])
        self.assertFalse(out["is_site"])
        self.assertEqual(out["others"][0]["label"], "bedsheet")
        self.assertEqual(out["verification"]["rejected"], 1)

    def test_shares_add_to_one_hundred(self):
        out = vlm._shape({"is_construction_site": True, "materials": [
            {"material": "Wood", "quantity": 100, "confidence": 0.6},
            {"material": "Metal", "quantity": 50, "confidence": 0.3},
            {"material": "Glass", "quantity": 10, "confidence": 0.1},
        ]})
        self.assertEqual(sum(d["share"] for d in out["dets"]), 100)

    def test_same_material_twice_is_one_detection(self):
        out = vlm._shape({"is_construction_site": True, "materials": [
            {"material": "Wood", "quantity": 100, "confidence": 0.4},
            {"material": "Wood", "quantity": 300, "confidence": 0.8},
        ]})
        self.assertEqual(len(out["dets"]), 1)
        self.assertEqual(out["dets"][0]["confidence"], 0.8)


class TestFailSoft(unittest.TestCase):
    def test_no_key_means_not_configured(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in ("VLM_API_KEY", "GEMINI_API_KEY"):
                os.environ.pop(name, None)
            self.assertFalse(vlm.configured())
            self.assertIsNone(vlm.vlm_detect(b"\xff\xd8\xff"))

    def test_ai_provider_local_forces_the_local_path(self):
        with mock.patch.dict(os.environ, {"VLM_API_KEY": "k", "AI_PROVIDER": "local"}):
            self.assertFalse(vlm.configured())

    def test_a_broken_reply_returns_none(self):
        # a 500, a timeout, or prose instead of JSON: the caller must fall back
        # to the local models rather than report an empty site
        with mock.patch.dict(os.environ, {"VLM_API_KEY": "k"}):
            with mock.patch.object(vlm, "_ask", side_effect=OSError("network down")):
                self.assertIsNone(vlm.vlm_detect(b"\xff\xd8"))


if __name__ == "__main__":
    unittest.main()
