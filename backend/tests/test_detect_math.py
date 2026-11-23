"""Tests for the per-pile detection geometry. No models, no weights."""

import unittest

from app.ai import detect_math


class TestOverlap(unittest.TestCase):
    def test_nested_boxes_have_low_iou_and_full_containment(self):
        iou, ios = detect_math.overlap_matrix([(0, 0, 10, 10), (0, 0, 20, 20)])
        self.assertAlmostEqual(float(iou[0, 1]), 0.25)
        self.assertAlmostEqual(float(ios[0, 1]), 1.0)

    def test_half_overlap(self):
        iou, ios = detect_math.overlap_matrix([(0, 0, 10, 10), (5, 0, 15, 10)])
        self.assertAlmostEqual(float(iou[0, 1]), 1 / 3)
        self.assertAlmostEqual(float(ios[0, 1]), 0.5)

    def test_disjoint_and_identical_boxes(self):
        iou, ios = detect_math.overlap_matrix([(0, 0, 10, 10), (50, 50, 60, 60)])
        self.assertEqual(float(iou[0, 1]), 0.0)
        self.assertEqual(float(ios[0, 1]), 0.0)

        iou, ios = detect_math.overlap_matrix([(0, 0, 10, 10), (0, 0, 10, 10)])
        self.assertAlmostEqual(float(iou[0, 1]), 1.0)
        self.assertAlmostEqual(float(ios[0, 1]), 1.0)

    def test_zero_area_box_does_not_divide_by_zero(self):
        iou, ios = detect_math.overlap_matrix([(5, 5, 5, 5), (0, 0, 10, 10)])
        self.assertEqual(float(iou[0, 1]), 0.0)
        self.assertEqual(float(ios[0, 1]), 0.0)


class TestSamePile(unittest.TestCase):
    def test_nested_boxes_are_one_pile(self):
        # a tight box on one brick inside the box on the whole stack: IoU is
        # only 0.25, so plain NMS would keep both and double the coverage
        merged = detect_math.merge_by_object([
            ("yolo-world", [("Bricks", 0.40, 0.20, (0, 0, 10, 10))]),
            ("yolov8n", [("Bricks", 0.70, 0.35, (0, 0, 20, 20))]),
        ])
        self.assertEqual(merged["Bricks"]["piles"], 1)
        self.assertEqual(merged["Bricks"]["cov"], 0.35)

    def test_overlapping_boxes_are_one_pile(self):
        merged = detect_math.merge_by_object([
            ("yolo-world", [("Wood", 0.55, 0.30, (0, 0, 100, 100))]),
            ("yolov8n", [("Wood", 0.62, 0.30, (5, 5, 100, 105))]),
        ])
        self.assertEqual(merged["Wood"]["piles"], 1)
        self.assertEqual(merged["Wood"]["cov"], 0.3)

    def test_grouping_follows_a_chain(self):
        # A matches B and B matches C, but A and C do not match each other.
        # tested on the matrix: at real thresholds three boxes rarely chain,
        # but the grouping has to be transitive when they do.
        import numpy as np

        same = np.array([
            [True, True, False],
            [True, True, True],
            [False, True, True],
        ])
        self.assertEqual(detect_math._groups(same), [[0, 1, 2]])


class TestDistinctPiles(unittest.TestCase):
    def test_two_piles_add_up(self):
        # the bug this fixes: both stacks used to collapse into one entry and
        # only the bigger coverage survived
        merged = detect_math.merge_by_object([
            ("yolo-world", [("Bricks", 0.70, 0.20, (0, 0, 50, 50))]),
            ("yolo-world", [("Bricks", 0.60, 0.25, (200, 200, 400, 400))]),
        ])
        self.assertEqual(merged["Bricks"]["piles"], 2)
        self.assertAlmostEqual(merged["Bricks"]["cov"], 0.45)
        self.assertEqual(merged["Bricks"]["conf"], 0.70)

    def test_coverage_cannot_pass_the_frame(self):
        merged = detect_math.merge_by_object([
            ("yolo-world", [
                ("Metal", 0.5, 0.8, (0, 0, 10, 10)),
                ("Metal", 0.5, 0.8, (100, 100, 110, 110)),
            ]),
        ])
        self.assertEqual(merged["Metal"]["cov"], detect_math.MAX_COVERAGE)


class TestMaterialsStaySeparate(unittest.TestCase):
    def test_same_box_different_materials_is_not_merged(self):
        # a pile of bricks on a concrete slab: real overlap, both are real
        merged = detect_math.merge_by_object([
            ("yolo-world", [("Bricks", 0.6, 0.2, (0, 0, 100, 100))]),
            ("yolo-world", [("Concrete", 0.5, 0.3, (0, 0, 100, 100))]),
        ])
        self.assertEqual(set(merged), {"Bricks", "Concrete"})
        self.assertEqual(merged["Bricks"]["cov"], 0.2)
        self.assertEqual(merged["Concrete"]["cov"], 0.3)

    def test_empty_passes_merge_to_nothing(self):
        self.assertEqual(detect_math.merge_by_object([]), {})
        self.assertEqual(detect_math.merge_by_object([("yolov8n", [])]), {})


class TestBookkeeping(unittest.TestCase):
    def test_sources_are_joined_once_each(self):
        merged = detect_math.merge_by_object([
            ("yolo-world", [
                ("Wood", 0.5, 0.1, (0, 0, 10, 10)),
                ("Wood", 0.5, 0.1, (90, 90, 100, 100)),
            ]),
            ("yolov8n", [("Wood", 0.6, 0.1, (0, 0, 10, 10))]),
        ])
        self.assertEqual(merged["Wood"]["source"], "yolo-world + yolov8n")

    def test_box_comes_from_the_strongest_view(self):
        merged = detect_math.merge_by_object([
            ("yolo-world", [("Wood", 0.40, 0.50, (0, 0, 300, 300))]),
            ("yolov8n", [("Wood", 0.90, 0.10, (0, 0, 10, 10))]),
        ])
        self.assertEqual(merged["Wood"]["box"], (0, 0, 10, 10))
        self.assertEqual(merged["Wood"]["cov"], 0.5)


class TestMergedContract(unittest.TestCase):
    def test_merge_hits_still_returns_the_ui_shape(self):
        from app.ai import vision

        merged = vision.merge_hits(
            [("Bricks", 0.40, 0.20, (0, 0, 10, 10))],
            [("Bricks", 0.70, 0.35, (0, 0, 20, 20))],
        )
        self.assertEqual(set(merged["Bricks"]), {"conf", "cov", "source", "box", "piles"})


if __name__ == "__main__":
    unittest.main()
