"""Seam under test: scoring.py — pure math, no I/O, no models.

Expected values are independent: haversine cross-checked against the
PostGIS ST_Distance measurement (5.2 km Koramangala→HSR), match scores
hand-computed from the 40/25/20/15 weights.
"""
import unittest

from scoring import haversine_km, match_score, qty_for


class TestHaversine(unittest.TestCase):
    def test_same_point_is_zero(self):
        self.assertEqual(haversine_km(12.9716, 77.5946, 12.9716, 77.5946), 0.0)

    def test_koramangala_to_hsr(self):
        # Verified against PostGIS: SELECT ST_Distance(...) → 5.2 km
        d = haversine_km(12.9716, 77.5946, 12.9352, 77.6245)
        self.assertAlmostEqual(d, 5.2, delta=0.2)

    def test_symmetry(self):
        a = haversine_km(12.9, 77.6, 13.0, 77.5)
        b = haversine_km(13.0, 77.5, 12.9, 77.6)
        self.assertAlmostEqual(a, b)


class TestQty(unittest.TestCase):
    def test_half_frame_bricks(self):
        self.assertEqual(qty_for("Bricks", 0.5), 2500)  # 5000 * 0.5

    def test_coverage_clamped_above_one(self):
        self.assertEqual(qty_for("Metal", 2.0), 1200)

    def test_tiny_coverage_still_counts_one(self):
        self.assertGreaterEqual(qty_for("Wood", 0.0), 1)

    def test_unknown_material_has_default_base(self):
        self.assertEqual(qty_for("Unobtainium", 1.0), 100)


class TestMatchScore(unittest.TestCase):
    def _listing(self, **kw):
        base = {"material": "Bricks", "quantity": 4000,
                "lat": 12.9352, "lng": 77.6245, "condition": "Fair"}
        base.update(kw)
        return base

    def test_perfect_match_scores_100(self):
        score, dist = match_score(self._listing(), "Bricks", 4000,
                                  12.9352, 77.6245, "Fair")
        self.assertEqual(score, 100.0)
        self.assertEqual(dist, 0.0)

    def test_wrong_material_loses_32_points(self):
        # material 0.2*40=8 instead of 40 → 68.0
        score, _ = match_score(self._listing(), "Wood", 4000,
                               12.9352, 77.6245, "Fair")
        self.assertEqual(score, 68.0)

    def test_far_away_loses_distance_points(self):
        # ~8500 km away → dist score 0, loses full 20
        score, dist = match_score(self._listing(), "Bricks", 4000,
                                  51.5, -0.12, "Fair")
        self.assertGreater(dist, 50)
        self.assertEqual(score, 80.0)

    def test_half_quantity_loses_half_qty_points(self):
        # qty ratio 0.5 → 12.5 instead of 25 → 87.5
        score, _ = match_score(self._listing(quantity=2000), "Bricks", 4000,
                               12.9352, 77.6245, "Fair")
        self.assertEqual(score, 87.5)


if __name__ == "__main__":
    unittest.main()
