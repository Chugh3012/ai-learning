import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_scout.lib import vectors

class TestVectorMath(unittest.TestCase):
    def test_pack_unpack_l2_normalizes(self):
        v = [3.0, 4.0] + [0.0] * 254
        u = vectors.unpack(vectors.pack(v))
        self.assertAlmostEqual(u[0], 0.6, places=5)
        self.assertAlmostEqual(u[1], 0.8, places=5)
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in u)), 1.0, places=5)

    def test_zero_vector_does_not_divide_by_zero(self):
        self.assertEqual(vectors.unpack(vectors.pack([0.0] * 256))[0], 0.0)

    def test_dot_of_normalized_is_cosine(self):
        a = vectors.normalize([1.0, 0.0])
        b = vectors.normalize([1.0, 1.0])
        self.assertAlmostEqual(vectors.dot(a, b), 1 / math.sqrt(2), places=5)

class TestMatchBonus(unittest.TestCase):
    def setUp(self):
        self.interest = vectors.normalize([1.0] + [0.0] * 255)
        self.vecs = {
            1: vectors.pack([1.0] + [0.0] * 255),
            2: vectors.pack([0.0, 1.0] + [0.0] * 254),
            3: vectors.pack([-1.0] + [0.0] * 255),
        }

    def test_orders_by_alignment(self):
        b = vectors.match_bonus(self.interest, self.vecs, weight=15.0)
        self.assertGreater(b[1], b[2])
        self.assertGreater(b[2], b[3])

    def test_mean_centered_sums_to_zero(self):
        b = vectors.match_bonus(self.interest, self.vecs, weight=15.0)
        self.assertAlmostEqual(sum(b.values()), 0.0, places=4)

    def test_weight_scales_spread(self):
        small = vectors.match_bonus(self.interest, self.vecs, weight=1.0)
        big = vectors.match_bonus(self.interest, self.vecs, weight=10.0)
        self.assertAlmostEqual(big[1], small[1] * 10, places=4)

    def test_no_interest_or_no_vecs_is_empty(self):
        self.assertEqual(vectors.match_bonus(None, self.vecs, 15.0), {})
        self.assertEqual(vectors.match_bonus(self.interest, {}, 15.0), {})

if __name__ == "__main__":
    unittest.main()
