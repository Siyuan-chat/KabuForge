import unittest

from framework_v2.strategy_registry import StrategyRegistry, StrategySpec, spec_from_config


class StrategyRegistryTests(unittest.TestCase):
    def test_register_and_create(self):
        registry = StrategyRegistry()
        spec = StrategySpec("test.strategy", "1")
        class TestStrategy:
            def decide(self, **kwargs):
                return None
        marker = TestStrategy()
        registry.register(spec, lambda config, factor_ids: marker)
        self.assertIs(registry.create(spec, {}, ()), marker)
        self.assertEqual(registry.catalog(), (spec,))

    def test_rejects_duplicate_and_unknown_specs(self):
        registry = StrategyRegistry()
        spec = StrategySpec("test.strategy", "1")
        registry.register(spec, lambda config, factor_ids: object())
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(spec, lambda config, factor_ids: object())
        with self.assertRaisesRegex(ValueError, "unknown strategy"):
            registry.require(StrategySpec("missing", "1"))

    def test_v1_config_resolves_to_composite_factor(self):
        from framework_v2.application import ApplicationService
        from framework_v2.strategy_registry import CompositeFactorStrategyAdapter
        config = {
            "kind": "strategy", "version": "1",
            "scoring": {"formula": "quality"},
            "portfolio": {"construction": "equal_weight", "parameters": {"top_n": 1}},
        }
        service = ApplicationService()
        spec = spec_from_config(config)
        strategy = service.strategy_registry.create(spec, config, ("quality",))
        self.assertEqual(spec, StrategySpec("composite_factor", "1"))
        self.assertIsInstance(strategy, CompositeFactorStrategyAdapter)


if __name__ == "__main__":
    unittest.main()
