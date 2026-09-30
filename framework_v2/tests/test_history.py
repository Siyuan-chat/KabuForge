import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from framework_v2.demo import create_demo
from framework_v2.history import run_history

class HistoryTests(unittest.TestCase):
    def test_next_open_changes_fill_not_precomputed_order_quantity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=create_demo(Path(temp)/"demo")
            timeline=json.loads((root/"timeline.json").read_text())
            session=timeline["sessions"][-1]
            timeline={"format":"execution.daily_bars.v2","sessions":[session]}
            session["execution_quotes"]=[dict(q) for q in session["quotes"]]
            (root/"daily.json").write_text(json.dumps(timeline))
            first=run_history(root/"backtest.json",root/"daily.json",output_dir=root/"first")
            for quote in session["execution_quotes"]:
                quote["bid"]=str(float(quote["bid"])*0.99)
                quote["ask"]=str(float(quote["ask"])*0.99)
            (root/"daily.json").write_text(json.dumps(timeline))
            second=run_history(root/"backtest.json",root/"daily.json",output_dir=root/"second")
            self.assertEqual(first["decisions"][0]["plan"],second["decisions"][0]["plan"])
            self.assertTrue(first["journal"]["fills"])
            self.assertNotEqual(first["nav"][0]["cash"],second["nav"][0]["cash"])

    def test_three_periods_same_modes_and_journal_cash_identity(self):
        from decimal import Decimal
        with tempfile.TemporaryDirectory() as temp, patch.object(socket.socket,"connect",side_effect=AssertionError("offline")):
            root=create_demo(Path(temp)/"demo")
            strategy=json.loads((root/"strategy.json").read_text())
            strategy["rebalance"]={"frequency":"daily"}
            (root/"strategy.json").write_text(json.dumps(strategy))
            reports=[run_history(root/(mode+".json"),root/"timeline.json",output_dir=root/mode) for mode in ("backtest","paper","fake")]
            for report in reports:
                self.assertEqual(len(report["decisions"]),3)
                self.assertEqual(len(report["nav"]),3)
                cash=Decimal(2000000)
                for row in report["journal"]["fills"]:
                    fill=json.loads(row["payload"]); value=Decimal(fill["price"])*fill["quantity"]
                    cash+=value if fill["side"]=="sell" else -value
                    cash-=Decimal(fill["fee"])
                self.assertEqual(cash,Decimal(report["nav"][-1]["cash"]))
            self.assertEqual(reports[0]["decisions"],reports[1]["decisions"])
            self.assertEqual(reports[0]["decisions"],reports[2]["decisions"])
            self.assertEqual(reports[0]["nav"],reports[2]["nav"])

if __name__=="__main__": unittest.main()
