"""Dashboard schemas."""
from typing import List, Optional
from pydantic import BaseModel


class DashboardStats(BaseModel):
    element_count: int = 0
    case_count: int = 0
    automated_count: int = 0
    point_count: int = 0


class DashboardToday(BaseModel):
    ai_calls: int = 0
    tokens_used: int = 0


class DistributionItem(BaseModel):
    type: str
    count: int = 0


class TrendItem(BaseModel):
    date: str
    call_count: int = 0
    tokens: int = 0


class OverviewResponse(BaseModel):
    stats: DashboardStats
    today: DashboardToday
    element_distribution: List[DistributionItem] = []
    case_distribution: List[DistributionItem] = []
    ai_trend: List[TrendItem] = []
