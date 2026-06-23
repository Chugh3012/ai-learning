import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import prism.lib.foundry as foundry
from prism.lib.gateway import ModelGateway

class TestModelGateway(unittest.TestCase):
    def test_model_for_from_config(self):
        g = ModelGateway("ep", default="mini")
        self.assertEqual(g.model_for("rank"), "mini")
        self.assertEqual(g.model_for("embed"), "embed")

    def test_unknown_task_falls_back_to_default(self):
        self.assertEqual(ModelGateway("ep", default="zzz").model_for("no-such-task"), "zzz")

class TestPerModelCost(unittest.TestCase):
    def setUp(self):
        foundry._BY_MODEL.clear()
        for k in foundry._USAGE:
            foundry._USAGE[k] = 0

    def tearDown(self):
        foundry._BY_MODEL.clear()

    def test_uses_per_model_pricing(self):
        foundry._BY_MODEL["mini"] = {"prompt": 1_000_000, "completion": 1_000_000}
        foundry._BY_MODEL["nano"] = {"prompt": 1_000_000, "completion": 0}
        pricing = {"mini": {"in": 0.40, "out": 1.60}, "nano": {"in": 0.10, "out": 0.40}}
        # mini 0.40+1.60=2.00, nano 0.10 -> 2.10
        self.assertAlmostEqual(foundry.cost_usd(pricing), 2.10, places=4)

    def test_unknown_model_uses_default_rates(self):
        foundry._BY_MODEL["mystery"] = {"prompt": 1_000_000, "completion": 0}
        self.assertAlmostEqual(foundry.cost_usd({}), 0.40, places=4)

    def test_empty_is_zero(self):
        self.assertEqual(foundry.cost_usd({}), 0.0)

if __name__ == "__main__":
    unittest.main()
