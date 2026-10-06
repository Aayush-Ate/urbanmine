"""Seam under test: catalog.py invariants.

No magic values — every prompt must resolve to a real material, every
material needs a quantity base, every price must be positive.
"""
import unittest

import catalog


class TestCatalog(unittest.TestCase):
    def test_sixteen_materials(self):
        self.assertEqual(len(catalog.MATERIAL_META), 16)

    def test_every_prompt_maps_to_known_material(self):
        for phrase, mat in catalog.WORLD_PROMPTS.items():
            self.assertIn(mat, catalog.MATERIAL_META, f"prompt {phrase!r}")

    def test_every_material_has_quantity_base(self):
        self.assertEqual(set(catalog.FULL_QTY), set(catalog.MATERIAL_META))

    def test_prices_and_co2_positive(self):
        for mat, meta in catalog.MATERIAL_META.items():
            self.assertGreater(meta["price"], 0, mat)
            self.assertGreater(meta["co2_per_unit_kg"], 0, mat)
            self.assertTrue(meta["unit"], mat)

    def test_coco_map_values_are_known_materials(self):
        for cls, mat in catalog.COCO_TO_MATERIAL.items():
            self.assertIn(mat, catalog.MATERIAL_META, f"COCO {cls!r}")

    def test_ignore_list_not_in_prompts(self):
        overlap = set(catalog.WORLD_IGNORE) & set(catalog.WORLD_PROMPTS)
        self.assertEqual(overlap, set())


if __name__ == "__main__":
    unittest.main()
