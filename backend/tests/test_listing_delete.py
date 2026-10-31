"""DELETE /api/listings/{id} removes the listing and leaves no dead photo.

Temp DATA_FILE, fake photo URLs, so the real database and uploads folder are
never touched.
"""
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.storage import store


class TestListingDelete(unittest.TestCase):
    def setUp(self):
        from app import main
        self.client = TestClient(main.app)
        self.tmp = tempfile.TemporaryDirectory()
        self.real_data_file = store.DATA_FILE
        store.DATA_FILE = Path(self.tmp.name) / "data.json"

    def tearDown(self):
        store.DATA_FILE = self.real_data_file
        self.tmp.cleanup()

    def _create(self, **extra):
        body = {"material": "Wood", "quantity": 10, "condition": "Good", "title": "Delete me"}
        body.update(extra)
        r = self.client.post("/api/listings", json=body)
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_delete_removes_it_from_the_marketplace(self):
        listing = self._create()
        r = self.client.delete(f"/api/listings/{listing['id']}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"deleted": listing["id"]})
        self.assertEqual(self.client.get("/api/listings").json(), [])

    def test_unknown_listing_is_a_404(self):
        r = self.client.delete("/api/listings/nope")
        self.assertEqual(r.status_code, 404)

    def test_shared_photo_survives_until_the_last_listing_goes(self):
        # both listings point at the same photo, so deleting one must not
        # leave the other pointing at a deleted file
        first = self._create(image_url="/uploads/keep.jpg", thumb_url="/uploads/tkeep.jpg")
        self._create(image_url="/uploads/keep.jpg", thumb_url="/uploads/tkeep.jpg")
        self.assertEqual(self.client.delete(f"/api/listings/{first['id']}").status_code, 200)
        left = self.client.get("/api/listings").json()
        self.assertEqual(len(left), 1)
        self.assertEqual(left[0]["image_url"], "/uploads/keep.jpg")


if __name__ == "__main__":
    unittest.main()
