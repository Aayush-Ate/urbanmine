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

    def test_empty_db_stays_empty(self):
        # no starter listings: the marketplace only shows what users add
        self.assertEqual(store.load_db()["listings"], [])


if __name__ == "__main__":
    unittest.main()
