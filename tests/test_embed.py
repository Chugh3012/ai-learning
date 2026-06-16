"""embed — two-tower vector math (pack/unpack/normalize, dot, z-scored interest bonus)."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import embed  # noqa: E402


class TestVectorMath(unittest.TestCase):
    def test_pack_unpack_l2_normalizes(self):
        v = [3.0, 4.0] + [0.0] * 254          # raw norm 5
        u = embed.unpack(embed.pack(v))
        self.assertAlmostEqual(u[0], 0.6, places=5)
        self.assertAlmostEqual(u[1], 0.8, places=5)
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in u)), 1.0, places=5)

    def test_zero_vector_does_not_divide_by_zero(self):
        self.assertEqual(embed.unpack(embed.pack([0.0] * 256))[0], 0.0)

    def test_dot_of_normalized_is_cosine(self):
        a = embed._normalize([1.0, 0.0])
        b = embed._normalize([1.0, 1.0])
        self.assertAlmostEqual(embed.dot(a, b), 1 / math.sqrt(2), places=5)


class TestMatchBonus(unittest.TestCase):
    def setUp(self):
        self.interest = embed._normalize([1.0] + [0.0] * 255)  # points at +x
        self.vecs = {
            1: embed.pack([1.0] + [0.0] * 255),       # cosine ~ +1
            2: embed.pack([0.0, 1.0] + [0.0] * 254),  # cosine 0
            3: embed.pack([-1.0] + [0.0] * 255),      # cosine ~ -1
        }

    def test_orders_by_alignment(self):
        b = embed.match_bonus(self.interest, self.vecs, weight=15.0)
        self.assertGreater(b[1], b[2])
        self.assertGreater(b[2], b[3])

    def test_mean_centered_sums_to_zero(self):
        b = embed.match_bonus(self.interest, self.vecs, weight=15.0)
        self.assertAlmostEqual(sum(b.values()), 0.0, places=4)

    def test_weight_scales_spread(self):
        small = embed.match_bonus(self.interest, self.vecs, weight=1.0)
        big = embed.match_bonus(self.interest, self.vecs, weight=10.0)
        self.assertAlmostEqual(big[1], small[1] * 10, places=4)

    def test_no_interest_or_no_vecs_is_empty(self):
        self.assertEqual(embed.match_bonus(None, self.vecs, 15.0), {})
        self.assertEqual(embed.match_bonus(self.interest, {}, 15.0), {})


if __name__ == "__main__":
    unittest.main()
