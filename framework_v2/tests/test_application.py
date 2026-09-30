import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from framework_v2.cli import plan_file
from framework_v2.demo import create_demo
from framework_v2.config import ConfigError

class ApplicationTests(unittest.TestCase):
    def test_offline_mode_parity_and_future_execution_does_not_reselect(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(socket.socket,"connect",side_effect=AssertionError("network forbidden")):
            root=create_demo(Path(temp)/"demo")
            run=lambda mode:plan_file(root/(mode+".json"),root/"execution.json","2024-05-01T09:00:00+09:00","2024-05-01T09:00:00+09:00")
            outputs=[run(mode) for mode in ("backtest","paper","fake")]
            self.assertTrue(outputs[0]["plan"]["intents"])
            self.assertEqual(outputs[0]["plan"],outputs[1]["plan"])
            self.assertEqual(outputs[0]["plan"],outputs[2]["plan"])
            self.assertEqual(outputs[0]["strategy_hash"],outputs[2]["strategy_hash"])
            execution=json.loads((root/"execution.json").read_text())
            for quote in execution["quotes"]: quote["ask"]="9999999"
            (root/"execution.json").write_text(json.dumps(execution))
            changed=run("paper")
            self.assertEqual(outputs[0]["decision"],changed["decision"])
            self.assertEqual(outputs[0]["risk"],changed["risk"])
            self.assertFalse(changed["plan"]["intents"])

    def test_snapshot_identity_change_rejected(self):
        from framework_v2.application import ApplicationService
        from framework_v2.local_io import context_from_file
        with tempfile.TemporaryDirectory() as temp:
            root=create_demo(Path(temp)/"demo")
            resolved=ApplicationService().validate(root/"paper.json")
            with (root/"snapshot.json").open("a") as stream: stream.write(" ")
            with self.assertRaisesRegex(ConfigError,"changed"):
                context_from_file(root/"snapshot.json",expected_hash=resolved.data_snapshot_hash,decision_at="2024-05-01T09:00:00+09:00")

if __name__=="__main__": unittest.main()
