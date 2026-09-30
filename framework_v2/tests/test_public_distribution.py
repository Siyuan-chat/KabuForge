"""The public distribution must not discover private workspace factor modules."""
import inspect
from pathlib import Path
import unittest

from framework_v2.factors import FactorContractError
from framework_v2.legacy_provider import BuiltinFactors


class PublicDistributionTests(unittest.TestCase):
    def test_only_public_sources_and_identities_are_installed(self):
        builtins = BuiltinFactors()
        self.assertEqual(set(builtins.versions), {
            'public.quality', 'public.value', 'public.momentum_12_1',
            'public.dual_ma', 'public.reversal', 'public.attention', 'public.behaviour',
        })
        public_root = Path(__file__).resolve().parents[2] / 'factors'
        for runner in builtins.runners.values():
            self.assertEqual(Path(inspect.getsourcefile(runner)).resolve().parent, public_root)

    def test_private_family_is_rejected(self):
        with self.assertRaisesRegex(FactorContractError, 'public factors only'):
            BuiltinFactors(family='private')
