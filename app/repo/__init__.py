"""
数据访问层 repo
负责和 Mongo 交互。
这一层只碰数据库，不碰分析和飞书。
"""
from .cls_telegraph import CLSTelegraphRepository
from .sector_3d_daily_summary_repository import Sector3DDailySummaryRepository
from .daily_market_analysis import DailyMarketAnalysisRepository
from .sector_investment_preference_ranking_repository import SectorInvestmentPreferenceRankingRepository
from .sector_market_heat_ranking_repository import SectorMarketHeatRankingRepository
from .daily_kline_snapshot import DailyKLineSnapshotRepository
from .daily_stock_technical_analysis_result_repository import DailyStockTechnicalAnalysisResultRepository, ClaimResult

__all__ = [
    "CLSTelegraphRepository",
    "Sector3DDailySummaryRepository",
    "DailyMarketAnalysisRepository",
    "SectorInvestmentPreferenceRankingRepository",
    "SectorMarketHeatRankingRepository",
    "DailyKLineSnapshotRepository",
    "DailyStockTechnicalAnalysisResultRepository",
    "ClaimResult",
]