"""Tests for the accuracy harness. Pure scoring, no models loaded."""

import json
import os
import tempfile
import unittest

from eval import harness


def rec(materials, **kw):
    return {"image": "x.jpg", "materials": materials, "coverage": kw.get("coverage", {})}


class TestScore(unittest.TestCase):
    def test_perfect_predictions(self):
        records = [rec(["Bricks"]), rec(["Wood"])]
        preds = [{"Bricks": 0.8}, {"Wood": 0.7}]
        stats = harness.score(records, preds)
        self.assertEqual(stats["Bricks"]["precision"], 1.0)
        self.assertEqual(stats["Bricks"]["recall"], 1.0)
        self.assertEqual(harness.macro_f1(stats), 1.0)

    def test_prediction_on_a_negative_photo_is_a_false_positive(self):
        # a bedroom labeled [] that the pipeline still called Bricks
        stats = harness.score([rec([])], [{"Bricks": 0.9}])
        self.assertEqual(stats["Bricks"]["precision"], 0.0)
        self.assertEqual(stats["Bricks"]["fp"], 1)

    def test_missed_material_is_a_false_negative(self):
        stats = harness.score([rec(["Metal"])], [{}])
        self.assertEqual(stats["Metal"]["recall"], 0.0)
        self.assertEqual(stats["Metal"]["fn"], 1)

    def test_a_confidence_cut_can_remove_a_hit(self):
        stats = harness.score([rec(["Wood"])], [{"Wood": 0.3}], cut=0.5)
        self.assertEqual(stats["Wood"]["recall"], 0.0)

    def test_no_records_does_not_divide_by_zero(self):
        self.assertEqual(harness.score([], []), {})
        self.assertEqual(harness.macro_f1({}), 0.0)


class TestSweep(unittest.TestCase):
    def test_picks_the_cut_that_separates_real_from_noise(self):
        # Bricks genuinely high (0.7, 0.8); a false positive on a bedroom at
        # 0.62. A cut above 0.62 keeps recall and drops the FP.
        records = [rec(["Bricks"]), rec(["Bricks"]), rec([])]
        candidates = [
            [("Bricks", 0.70)], [("Bricks", 0.80)], [("Bricks", 0.62)],
        ]
        out = harness.sweep_cut(records, candidates)
        self.assertGreater(out["Bricks"]["cut"], 0.62)
        self.assertEqual(out["Bricks"]["f1"], 1.0)

    def test_materials_absent_from_truth_are_not_suggested(self):
        out = harness.sweep_cut([rec(["Wood"])], [[("Metal", 0.9)]])
        self.assertEqual(set(out), {"Wood"})


class TestQuantityError(unittest.TestCase):
    def test_measures_coverage_against_the_label(self):
        records = [rec(["Bricks"], coverage={"Bricks": 0.5})]
        dets = [[{"material": "Bricks", "coverage": 0.4}]]
        self.assertAlmostEqual(harness.quantity_error(records, dets), 0.1)

    def test_missing_material_counts_as_zero_coverage(self):
        records = [rec(["Bricks"], coverage={"Bricks": 0.5})]
        self.assertAlmostEqual(harness.quantity_error(records, [[]]), 0.5)

    def test_no_labels_means_no_number(self):
        self.assertIsNone(harness.quantity_error([rec(["Wood"])], [[{}]]))


class TestManifest(unittest.TestCase):
    def _write(self, lines):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(lines))
        self.addCleanup(os.remove, path)
        return path

    def test_comments_and_blank_lines_are_skipped(self):
        path = self._write([
            "# header", "",
            json.dumps({"image": "a.jpg", "materials": ["Wood"]}),
        ])
        self.assertEqual(len(harness.load_manifest(path)), 1)

    def test_missing_image_is_an_error(self):
        path = self._write([json.dumps({"materials": []})])
        with self.assertRaises(ValueError):
            harness.load_manifest(path)

    def test_materials_must_be_a_list(self):
        path = self._write([json.dumps({"image": "a.jpg", "materials": "Wood"})])
        with self.assertRaises(ValueError):
            harness.load_manifest(path)

    def test_bad_json_names_the_line(self):
        path = self._write([json.dumps({"image": "a.jpg", "materials": []}), "{oops"])
        with self.assertRaises(ValueError) as ctx:
            harness.load_manifest(path)
        self.assertIn(":2", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
