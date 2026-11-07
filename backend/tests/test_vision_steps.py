"""Tests for the small vision steps. No model weights are loaded here."""
import os
import types
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from app.ai import vision


class TestMaskCoverage(unittest.TestCase):
    def test_mask_fraction_beats_the_bounding_box(self):
        # a ragged pile fills half its box; the mask says so
        res = types.SimpleNamespace(
            masks=types.SimpleNamespace(data=[np.array([[1.0, 1.0], [0.0, 0.0]])]))
        self.assertAlmostEqual(vision._mask_area(res, 0), 0.5)

    def test_detector_only_results_report_no_mask(self):
        self.assertEqual(vision._mask_area(types.SimpleNamespace(masks=None), 0), 0.0)
        self.assertEqual(vision._mask_area(types.SimpleNamespace(), 0), 0.0)

    def test_a_bad_index_is_not_fatal(self):
        res = types.SimpleNamespace(masks=types.SimpleNamespace(data=[]))
        self.assertEqual(vision._mask_area(res, 3), 0.0)


class TestWorldLoader(unittest.TestCase):
    """The default open-vocab model is YOLOE; a *world* path still loads."""

    def setUp(self):
        self._saved = vision.world_model
        vision.world_model = None

    def tearDown(self):
        vision.world_model = self._saved

    def _fake_ultralytics(self):
        calls = {}

        class Stub:
            def __init__(self, path):
                self.path = path
                calls["path"] = path

            def set_classes(self, names):
                calls["classes"] = list(names)
                return dict(enumerate(names))

        return types.SimpleNamespace(YOLO=Stub, YOLOE=Stub), calls

    def test_default_weights_load_through_yoloe(self):
        fake, calls = self._fake_ultralytics()
        with mock.patch.dict("sys.modules", {"ultralytics": fake}), \
                mock.patch.dict(os.environ, {"WORLD_MODEL_PATH": ""}):
            vision._load_world()
        self.assertEqual(calls["path"], "yoloe-11s-seg.pt")
        self.assertEqual(calls["classes"], vision.WORLD_CLASSES)
        self.assertTrue(vision.world_model)

    def test_world_checkpoint_still_uses_plain_yolo(self):
        # the revert path has to keep working
        fake, calls = self._fake_ultralytics()
        with mock.patch.dict("sys.modules", {"ultralytics": fake}), \
                mock.patch.dict(os.environ, {"WORLD_MODEL_PATH": "yolov8m-worldv2.pt"}):
            vision._load_world()
        self.assertEqual(calls["path"], "yolov8m-worldv2.pt")
        self.assertTrue(vision.world_model)

    def test_a_broken_import_leaves_world_model_false(self):
        with mock.patch.dict("sys.modules", {"ultralytics": None}), \
                mock.patch.dict(os.environ, {"WORLD_MODEL_PATH": ""}):
            vision._load_world()
        self.assertIs(vision.world_model, False)


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
        self.assertEqual(dets[0]["mode"], "area")

    def test_visual_hit_without_a_box_has_no_bbox(self):
        merged = {"Concrete": {"conf": 0.4, "cov": 0.3, "source": "visual estimate"}}
        dets = vision.build_detections(merged, "Fair", (200, 400))
        self.assertIsNone(dets[0]["bbox"])


class TestSuggestedPrice(unittest.TestCase):
    def test_price_follows_the_guessed_condition(self):
        # Plywood base is ₹30/sq ft: Good pays 85%, Poor pays 40%
        merged = {"Plywood": {"conf": 0.6, "cov": 0.5, "source": "yolo-world"}}
        good = vision.build_detections(merged, "Good")[0]["suggested_price_per_unit"]
        poor = vision.build_detections(merged, "Poor")[0]["suggested_price_per_unit"]
        self.assertEqual(good, 26)
        self.assertEqual(poor, 12)
        self.assertLess(poor, good)


class TestShares(unittest.TestCase):
    def test_shares_add_to_one_hundred(self):
        dets = [{"confidence": 0.6}, {"confidence": 0.3}, {"confidence": 0.1}]
        out = vision.normalize_shares(dets)
        self.assertEqual(sum(d["share"] for d in out), 100)

    def test_empty_list_stays_empty(self):
        self.assertEqual(vision.normalize_shares([]), [])


class TestHouseholdRules(unittest.TestCase):
    def test_household_frame_drops_bed_as_wood(self):
        # clip says this aint a site, yolov8n sees a bed and calls it wood
        merged = {"Wood": {"conf": 0.8, "cov": 0.4, "source": "yolov8n"}}
        kept, others = vision.drop_household_hits(merged, [], False)
        self.assertEqual(kept, {})
        self.assertTrue(any("household item" in o["label"] for o in others))

    def test_person_on_a_site_keeps_the_wood(self):
        # worker next to a wood pile is still a wood pile
        merged = {"Wood": {"conf": 0.8, "cov": 0.4, "source": "yolov8n"}}
        others = [{"label": "person", "confidence": 0.9}]
        kept, _others = vision.drop_household_hits(merged, others, True)
        self.assertIn("Wood", kept)

    def test_bedsheet_drops_furniture_hit(self):
        # bedsheet in frame = bedroom photo. dont list the bed as wood.
        merged = {"Wood": {"conf": 0.8, "cov": 0.4, "source": "yolov8n + visual"}}
        others = [{"label": "bedsheet", "confidence": 0.7}]
        kept, _others = vision.drop_household_hits(merged, others, True)
        self.assertEqual(kept, {})

    def test_world_material_survives_a_household_frame(self):
        # yolo-world found a real material, keep it
        merged = {"Wood": {"conf": 0.8, "cov": 0.4, "source": "yolo-world"}}
        kept, _others = vision.drop_household_hits(merged, [], False)
        self.assertIn("Wood", kept)

    def test_clean_site_keeps_everything(self):
        merged = {
            "Wood": {"conf": 0.8, "cov": 0.4, "source": "yolov8n"},
            "Concrete": {"conf": 0.5, "cov": 0.3, "source": "yolo-world + visual"},
        }
        kept, others = vision.drop_household_hits(merged, [], True)
        self.assertEqual(set(kept), {"Wood", "Concrete"})
        self.assertEqual(others, [])

    def test_site_verdict(self):
        real = {"Wood": {"conf": 0.8, "cov": 0.3, "source": "yolov8n"}}
        self.assertTrue(vision.is_construction_site(real))
        self.assertFalse(vision.is_construction_site({}))


class TestClipBoxes(unittest.TestCase):
    def test_crops_of_returns_one_crop_per_box(self):
        crops = vision.crops_of(red_image(), [(0, 0, 20, 20, 0.2), (10, 10, 60, 60, 0.3)])
        self.assertEqual(len(crops), 2)

    def test_weak_box_below_gate_is_rejected(self):
        hits = [
            ("Wood", 0.90, 0.20, (0, 0, 50, 50)),
            ("Concrete", 0.20, 0.30, (10, 10, 60, 60)),
        ]
        with mock.patch("app.ai.vision.clip_check", return_value=[0.90, 0.20]):
            kept, rejected, checked = vision.clip_filter_hits(red_image(), hits)
        self.assertEqual([h[0] for h in kept], ["Wood"])
        self.assertEqual(rejected[0]["material"], "Concrete")
        self.assertEqual(checked, 2)

    def test_confident_box_is_also_checked(self):
        # model can be confident and wrong. a pen at 0.80 still aint metal.
        hits = [("Metal", 0.80, 0.31, (10, 10, 60, 60))]
        with mock.patch("app.ai.vision.clip_check", return_value=[0.05]):
            kept, rejected, checked = vision.clip_filter_hits(red_image(), hits)
        self.assertEqual(kept, [])
        self.assertEqual(rejected[0]["material"], "Metal")
        self.assertEqual(checked, 1)

    def test_weak_box_above_gate_is_kept(self):
        hits = [("Concrete", 0.20, 0.30, (10, 10, 60, 60))]
        with mock.patch("app.ai.vision.clip_check", return_value=[0.80]):
            kept, rejected, checked = vision.clip_filter_hits(red_image(), hits)
        self.assertEqual([h[0] for h in kept], ["Concrete"])
        self.assertEqual(rejected, [])
        self.assertEqual(checked, 1)


if __name__ == "__main__":
    unittest.main()
