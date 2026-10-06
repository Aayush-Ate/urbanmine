"""Tests for store.py save and load, using a temp dir. The real data.json is
never touched. Each test points DATA_FILE at its own file instead."""
import tempfile
import unittest
from pathlib import Path

import store


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.real_data_file = store.DATA_FILE
        store.DATA_FILE = Path(self.tmp.name) / "data.json"

    def tearDown(self):
        store.DATA_FILE = self.real_data_file
        self.tmp.cleanup()

    def test_empty_db_shape(self):
        self.assertEqual(store.load_db(), {"listings": [], "requests": []})

    def test_save_then_load_round_trip(self):
        db = {"listings": [{"id": "abc", "material": "Wood"}], "requests": []}
        store.save_db(db)
        self.assertEqual(store.load_db(), db)

    def test_seed_creates_six_active_listings(self):
        db = store.seed_if_empty()
        self.assertEqual(len(db["listings"]), 6)
        self.assertTrue(all(l["status"] == "active" for l in db["listings"]))

    def test_seed_does_not_overwrite(self):
        store.seed_if_empty()
        db = store.load_db()
        db["listings"].append({"id": "mine"})
        store.save_db(db)
        self.assertEqual(len(store.seed_if_empty()["listings"]), 7)


if __name__ == "__main__":
    unittest.main()
