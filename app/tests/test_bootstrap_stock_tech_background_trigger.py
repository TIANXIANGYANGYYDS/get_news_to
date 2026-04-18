import unittest
from pathlib import Path


class BootstrapStockTechBackgroundTriggerTests(unittest.TestCase):
    def test_use_background_trigger_in_send_daily_market_analysis(self):
        source = Path("app/bootstrap.py").read_text(encoding="utf-8")
        send_daily_start = source.find("async def send_daily_market_analysis_card")
        self.assertGreater(send_daily_start, 0)
        send_daily_body = source[send_daily_start:]

        self.assertIn(
            "self._trigger_daily_stock_technical_analysis_background(analysis_trade_date=analysis_date)",
            send_daily_body,
        )
        self.assertNotIn(
            "await self.daily_stock_technical_analysis_service.run_once(",
            send_daily_body,
        )


if __name__ == "__main__":
    unittest.main()
