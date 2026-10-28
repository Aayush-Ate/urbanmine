"""Tests for the small vision steps. No model weights are loaded here."""
import unittest
from unittest import mock

from PIL import Image

import vision


def red_image():
    return Image.new("RGB", (100, 100), color=(200, 30, 30))


class TestMergeHits(unittest.TestCase):
    def test_keeps_higher_confidence_and_coverage(self):
        world = [("Bricks", 0.40, 0.20, (0, 0, 10, 10))]
        yolo = [("Bricks", 0.70, 0.35, (0, 0, 20, 20))]
        merged = vision.merge_hits(world, yolo)
        self.assertEqual(merged["Bricks"]["conf"], 0.70)
        self.assertEqual(merged["Bricks"]["cov"], 0.35)
        self.assertEqual(merged["Bricks"]["box"], (0, 0, 20, 20))
        self.assertIn("yolo-world", merged["Bricks"]["source"])
        self.assertIn("yolov8n", merged["Bricks"]["source"])

    def test_keeps_materials_only_one_model_saw(self):
        merged = vision.merge_hits([("Wood", 0.5, 0.2, (0, 0, 5, 5))],
                                   [("Metal", 0.6, 0.3, (0, 0, 6, 6))])
        self.assertEqual(set(merged), {"Wood", "Metal"})


class TestDetectionShape(unittest.TestCase):
    def test_bbox_is_normalized_to_the_frame(self):
        merged = {"Wood": {"conf": 0.8, "cov": 0.2, "source": "yolov8n",
                           "box": (10, 20, 110, 220)}}
        dets = vision.build_detections(merged, "Good", (200, 400))
        self.assertEqual(dets[0]["bbox"], [0.05, 0.05, 0.55, 0.55])
        self.assertNotIn("icon", dets[0])

    def test_visual_hit_without_a_box_has_no_bbox(self):
        merged = {"Concrete": {"conf": 0.4, "cov": 0.3, "source": "visual estimate"}}
        dets = vision.build_detections(merged, "Fair", (200, 400))
        self.assertIsNone(dets[0]["bbox"])


class TestShares(unittest.TestCase):
    def test_shares_add_to_one_hundred(self):
        dets = [{"confidence": 0.6}, {"confidence": 0.3}, {"confidence": 0.1}]
        out = vision.normalize_shares(dets)
        self.assertEqual(sum(d["share"] for d in out), 100)

    def test_empty_list_stays_empty(self):
        self.assertEqual(vision.normalize_shares([]), [])


class TestHouseholdRules(unittest.TestCase):
    def test_person_drops_visual_only_hit(self):
        merged = {"Concrete": {"conf": 0.6, "cov": 0.4, "source": "visual estimate"}}
        others = [{"label": "person", "confidence": 0.9}]
        kept, others, has_subject = vision.drop_household_hits(merged, others)
        self.assertEqual(kept, {})
        self.assertTrue(has_subject)
        self.assertTrue(any("background" in o["label"] for o in others))

    def test_model_hit_survives_a_person(self):
        merged = {"Wood": {"conf": 0.8, "cov": 0.4, "source": "yolov8n"}}
        others = [{"label": "person", "confidence": 0.9}]
        kept, _others, _has_subject = vision.drop_household_hits(merged, others)
        self.assertIn("Wood", kept)

    def test_fallback_only_on_clean_construction_frame(self):
        self.assertEqual(vision.fallback_guess({}, True, 0.0, False)["Concrete"]["conf"], 0.30)
        self.assertEqual(vision.fallback_guess({}, False, 0.0, False), {})
        self.assertEqual(vision.fallback_guess({}, True, 0.9, False), {})
        self.assertEqual(vision.fallback_guess({}, True, 0.0, True), {})

    def test_site_verdict(self):
        real = {"Wood": {"conf": 0.8, "cov": 0.3, "source": "yolov8n"}}
        fallback = {"Concrete": {"conf": 0.3, "cov": 0.1, "source": "fallback (low-confidence guess)"}}
        self.assertTrue(vision.is_construction_site(real, False))
        self.assertTrue(vision.is_construction_site(fallback, True))
        self.assertFalse(vision.is_construction_site(fallback, False))
        self.assertFalse(vision.is_construction_site({}, True))


class TestClipBoxes(unittest.TestCase):
    def test_crops_of_returns_one_crop_per_box(self):
        crops = vision.crops_of(red_image(), [(0, 0, 20, 20, 0.2), (10, 10, 60, 60, 0.3)])
        self.assertEqual(len(crops), 2)

    def test_weak_box_below_gate_is_rejected(self):
        hits = [
            ("Wood", 0.90, 0.20, (0, 0, 50, 50)),
            ("Concrete", 0.20, 0.30, (10, 10, 60, 60)),
        ]
        with mock.patch("vision.clip_check", return_value=[0.20]):
            kept, rejected = vision.clip_filter_hits(red_image(), hits)
        self.assertEqual([h[0] for h in kept], ["Wood"])
        self.assertEqual(rejected[0]["material"], "Concrete")

    def test_weak_box_above_gate_is_kept(self):
        hits = [("Concrete", 0.20, 0.30, (10, 10, 60, 60))]
        with mock.patch("vision.clip_check", return_value=[0.80]):
            kept, rejected = vision.clip_filter_hits(red_image(), hits)
        self.assertEqual([h[0] for h in kept], ["Concrete"])
        self.assertEqual(rejected, [])


if __name__ == "__main__":
    unittest.main()
