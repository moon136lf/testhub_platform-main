"""AI 诊断 API (#5c) — §9.2.5 /diagnostics/analyze + /apply."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.storage import storage_client
from app.schemas.diagnostics import AnalyzeRequest, ApplyRequest, DiagResponse
from app.services.ai_gateway import AIGateway
from app.services.diagnostics_service import DiagnosticsService

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_svc(db: AsyncSession = Depends(get_db)) -> DiagnosticsService:
    return DiagnosticsService(db=db, gateway=AIGateway(), storage=storage_client)


@router.post("/analyze")
async def analyze(request: AnalyzeRequest,
                  svc: DiagnosticsService = Depends(_get_svc)) -> DiagResponse:
    """TRANS-05: execution_id 自动取数打包发 AI (kimi2.6 多模态)."""
    try:
        data = await svc.analyze(
            request.execution_id, step=request.step,
            override=request.error_data.model_dump() if request.error_data else None,
        )
        return DiagResponse(data=data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConnectionError as e:
        # gateway provider 未配置 (moonshot 无 key)
        raise HTTPException(status_code=503, detail=f"AI 服务不可用: {e}")
    except Exception as e:
        logger.error(f"diagnose analyze failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI 诊断失败: {e}")


@router.post("/apply")
async def apply_fix(request: ApplyRequest,
                    svc: DiagnosticsService = Depends(_get_svc)) -> DiagResponse:
    """TRANS-06: 应用修复 — new_locator 清洗后回写元素库 (source=ai_fixed)."""
    try:
        data = await svc.apply(
            project_id=request.project_id, element_name=request.element_name,
            new_locator=request.new_locator, confidence=request.confidence,
        )
        return DiagResponse(data=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"diagnose apply failed: {e}")
        raise HTTPException(status_code=502, detail=f"应用修复失败: {e}")
