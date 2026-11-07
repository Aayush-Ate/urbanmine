"""The per-material confidence floors.

One global threshold was the reason a 13% brick box became a listing while a
real window frame at 19% was thrown away. These pin the table's shape and the
box loop that applies it — a stricter material inside the same photo must be
dropped while a looser one survives.
"""
import unittest

from app.ai.vision import _run_infer
from app.core.catalog import (
    MATERIAL_META,
    WORLD_CONF,
    WORLD_CONF_BY_MATERIAL,
    WORLD_IGNORE,
    WORLD_NONCON,
    WORLD_PROMPTS,
)


class _Box:
    """Just enough of an ultralytics Box: indexable cls/conf/xyxy/xywhn."""

    def __init__(self, cls_id, conf, area=0.16):
        side = area ** 0.5
        self.cls = [cls_id]
        self.conf = [conf]
        self.xyxy = [[10.0, 10.0, 10.0 + side * 100, 10.0 + side * 100]]
        self.xywhn = [[0.5, 0.5, side, side]]


class _Result:
    def __init__(self, boxes, names):
        self.boxes = boxes
        self.names = names


class _Model:
    """Returns whatever boxes it was built with, ignoring the image."""

    def __init__(self, boxes, names):
        self._boxes = boxes
        self._names = names

    def __call__(self, image, verbose=False, conf=0.0):
        return [_Result([b for b in self._boxes if b.conf[0] >= conf], self._names)]


class TestThresholdTable(unittest.TestCase):
    def test_every_material_has_a_threshold(self):
        missing = set(MATERIAL_META) - set(WORLD_CONF_BY_MATERIAL)
        self.assertFalse(missing, f"no threshold for: {sorted(missing)}")

    def test_no_threshold_for_an_unknown_material(self):
        unknown = set(WORLD_CONF_BY_MATERIAL) - set(MATERIAL_META)
        self.assertFalse(unknown, f"threshold for unknown material: {sorted(unknown)}")

    def test_every_prompt_maps_to_a_material_with_a_threshold(self):
        for prompt, material in WORLD_PROMPTS.items():
            self.assertIn(material, WORLD_CONF_BY_MATERIAL, prompt)

    def test_thresholds_are_positive_and_sane(self):
        for material, value in WORLD_CONF_BY_MATERIAL.items():
            self.assertGreater(value, 0.0, material)
            self.assertLessEqual(value, 0.6, material)

    def test_the_table_is_not_flat(self):
        # A looser-than-global floor is deliberate: doors and windows are rare
        # in pre-training, so the old 0.20 cut was already too high for them.
        values = WORLD_CONF_BY_MATERIAL.values()
        self.assertTrue(any(v > WORLD_CONF for v in values), "nothing stricter")
        self.assertTrue(any(v < WORLD_CONF for v in values), "nothing looser")

    def test_confusable_materials_are_stricter_than_distinctive_ones(self):
        # Glass and copper wire look like windows and pipes respectively.
        self.assertGreater(WORLD_CONF_BY_MATERIAL["Glass"],
                           WORLD_CONF_BY_MATERIAL["Doors"])
        self.assertGreater(WORLD_CONF_BY_MATERIAL["Copper"],
                           WORLD_CONF_BY_MATERIAL["Windows"])


class TestThresholdIsApplied(unittest.TestCase):
    def setUp(self):
        self.names = {0: "stack of hollow bricks", 1: "window frame without glass"}
        # Same confidence for both prompts: only the threshold can separate them.
        self.model = _Model([_Box(0, 0.22), _Box(1, 0.22)], self.names)

    def _hits(self):
        boxes = ["stack of hollow bricks", "window frame without glass"]
        names = {i: n for i, n in enumerate(boxes)}
        model = _Model([_Box(0, 0.22), _Box(1, 0.22)], names)
        return _run_infer(
            model, None, 0.10, WORLD_PROMPTS.get, WORLD_IGNORE, WORLD_NONCON,
            threshold_for=lambda m: WORLD_CONF_BY_MATERIAL.get(m, WORLD_CONF),
        )[0]

    def test_a_weak_brick_box_is_dropped(self):
        materials = [h[0] for h in self._hits()]
        self.assertNotIn("Bricks", materials)   # floor 0.30 > 0.22

    def test_the_same_confidence_keeps_the_window(self):
        materials = [h[0] for h in self._hits()]
        self.assertIn("Windows", materials)     # floor 0.18 < 0.22

    def test_without_per_material_thresholds_both_survive(self):
        # The old behaviour: one floor, so both boxes became listings.
        names = {0: "stack of hollow bricks", 1: "window frame without glass"}
        model = _Model([_Box(0, 0.22), _Box(1, 0.22)], names)
        hits, _ = _run_infer(model, None, 0.10, WORLD_PROMPTS.get,
                             WORLD_IGNORE, WORLD_NONCON)
        self.assertEqual({h[0] for h in hits}, {"Bricks", "Windows"})


if __name__ == "__main__":
    unittest.main()
