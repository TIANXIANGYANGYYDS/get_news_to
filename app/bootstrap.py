"""Legacy compatibility module.

This module is intentionally kept as a thin bridge so old imports do not break.
All business orchestration has been migrated to `server.app_factory` and service layers.
"""

from server.app_factory import create_app


class Application:  # compatibility facade
    def __init__(self):
        self.app = create_app()

    async def startup(self):
        return None

    async def shutdown(self):
        return None

    async def send_daily_market_analysis_card(self):
        return None
