"""
Models module initialization
"""

from app.models.project import Project
from app.models.test_case import TestPoint, TestCase, ScriptAsset, CaseVersion
from app.models.script import ConvertSession
from app.models.element import PageRepository, ElementRepository, FetchHistory, ChangeDetection, SelfHealCache
from app.models.execution import ExecutionRecord, AICallLog, ExecutionDetail
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
from app.models.test_rule import TestRule
from app.models.generation import GenerationSession, HallucinationConfig
from app.models.system import SystemSetting, TestEnv, TokenQuota, OperationLog
from app.models.regression import RegressionSet

__all__ = [
    "Project",
    "TestPoint",
    "TestCase",
    "ScriptAsset",
    "CaseVersion",
    "ConvertSession",
    "PageRepository",
    "ElementRepository",
    "FetchHistory",
    "ChangeDetection",
    "SelfHealCache",
    "ExecutionRecord",
    "AICallLog",
    "ExecutionDetail",
    "KnowledgeDocument",
    "KnowledgeChunk",
    "GenerationSession",
    "HallucinationConfig",
    "TestRule",
    "SystemSetting",
    "TestEnv",
    "TokenQuota",
    "OperationLog",
    "RegressionSet",
]
