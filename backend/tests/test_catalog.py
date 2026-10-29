"""Tests for catalog.py. They check the catalog holds together: each prompt
names a real material, each material has a quantity base, each price is
positive."""
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

    def test_prices_positive(self):
        for mat, meta in catalog.MATERIAL_META.items():
            self.assertGreater(meta["price"], 0, mat)
            self.assertTrue(meta["unit"], mat)

    def test_condition_price_covers_every_condition(self):
        self.assertEqual(set(catalog.CONDITION_PRICE), set(catalog.CONDITION_SCORES))
        for name, mult in catalog.CONDITION_PRICE.items():
            self.assertGreater(mult, 0, name)
            self.assertLessEqual(mult, 1, name)

    def test_coco_map_values_are_known_materials(self):
        for cls, mat in catalog.COCO_TO_MATERIAL.items():
            self.assertIn(mat, catalog.MATERIAL_META, f"COCO {cls!r}")

    def test_ignore_list_not_in_prompts(self):
        overlap = set(catalog.WORLD_IGNORE) & set(catalog.WORLD_PROMPTS)
        self.assertEqual(overlap, set())


if __name__ == "__main__":
    unittest.main()
