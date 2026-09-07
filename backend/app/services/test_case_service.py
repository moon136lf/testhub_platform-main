"""
Test Case Service - CRUD, filtering, batch operations, and statistics
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, func, and_, or_, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.test_case import TestCase, TestPoint, CaseVersion
from app.schemas.test_case import (
    CaseCreateRequest,
    CaseUpdateRequest,
    CaseFilterParams,
    BatchOperationRequest,
    CaseResponse,
    CaseDetailResponse,
    CaseListResponse,
    CaseStatsResponse,
)

logger = logging.getLogger(__name__)


class TestCaseService:
    """Test case service for managing test cases"""

    def __init__(self, db: AsyncSession):
        """
        Initialize test case service

        Args:
            db: Async database session
        """
        self.db = db

    _SNAPSHOT_FIELDS = ("name", "priority", "case_type", "automation_status",
                        "precondition", "steps", "expected_result")

    def _snapshot_dict(self, case: TestCase) -> dict:
        return {f: getattr(case, f) for f in self._SNAPSHOT_FIELDS}

    def _diff_summary(self, old: dict, new: dict) -> str:
        changed = [f for f in self._SNAPSHOT_FIELDS if old.get(f) != new.get(f)]
        return "变更字段: " + ", ".join(changed) if changed else "无字段变更"

    def _to_detail(self, case: TestCase) -> CaseDetailResponse:
        # steps 归一化：AI 生成的步骤可能缺 step 序号字段（{action,target,data,expected}），
        # StepSchema 要求 step>=1，缺失时按顺序重编号，避免详情接口 400
        steps = []
        for i, s in enumerate(case.steps or [], 1):
            if not isinstance(s, dict):
                continue
            s = dict(s)
            if not isinstance(s.get("step"), int) or s["step"] < 1:
                s["step"] = i
            steps.append(s)
        return CaseDetailResponse(
            id=str(case.id), project_id=str(case.project_id),
            point_id=str(case.point_id) if case.point_id else None,
            name=case.name, priority=case.priority, case_type=case.case_type,
            automation_status=case.automation_status, precondition=case.precondition,
            steps=steps, expected_result=case.expected_result,
            is_finalized=case.is_finalized, version=case.version,
            hallucination_status=case.hallucination_status, created_by=case.created_by,
            created_at=case.created_at.isoformat() if case.created_at else "",
            updated_at=case.updated_at.isoformat() if case.updated_at else "",
            is_deleted=case.is_deleted,
            review_status=getattr(case, "review_status", "pending") or "pending",
            review_comment=getattr(case, "review_comment", None),
            feasibility_level=getattr(case, "feasibility_level", None),
            cannot_automate_reason=getattr(case, "cannot_automate_reason", None),
            refinement_report=getattr(case, "refinement_report", None),
            refined_at=case.refined_at.isoformat() if getattr(case, "refined_at", None) else None,
        )

    def _build_query_filters(self, filters: CaseFilterParams) -> List:
        """
        Build dynamic query filters based on filter parameters

        Args:
            filters: Filter parameters

        Returns:
            List of SQLAlchemy filter conditions
        """
        conditions = [TestCase.is_deleted.is_(False)]

        # Required project_id filter
        conditions.append(TestCase.project_id == UUID(filters.project_id))

        # Optional filters
        if filters.point_id:
            conditions.append(TestCase.point_id == UUID(filters.point_id))

        if filters.priority:
            conditions.append(TestCase.priority == filters.priority)

        if filters.case_type:
            conditions.append(TestCase.case_type == filters.case_type)

        if filters.automation_status:
            conditions.append(TestCase.automation_status == filters.automation_status)

        if filters.is_finalized is not None:
            conditions.append(TestCase.is_finalized == filters.is_finalized)

        if filters.hallucination_status:
            conditions.append(TestCase.hallucination_status == filters.hallucination_status)

        # Keyword search in name, precondition, and expected_result
        if filters.keyword:
            keyword_pattern = f"%{filters.keyword}%"
            conditions.append(
                or_(
                    TestCase.name.ilike(keyword_pattern),
                    TestCase.precondition.ilike(keyword_pattern),
                    TestCase.expected_result.ilike(keyword_pattern)
                )
            )

        return conditions

    async def list_cases(self, filters: CaseFilterParams) -> CaseListResponse:
        """
        List test cases with filtering and pagination

        Args:
            filters: Filter and pagination parameters

        Returns:
            CaseListResponse with paginated results
        """
        try:
            # Build base query with filters
            conditions = self._build_query_filters(filters)

            # Count total records
            count_query = select(func.count()).select_from(TestCase).where(and_(*conditions))
            count_result = await self.db.execute(count_query)
            total = count_result.scalar() or 0

            # Apply pagination and ordering with LEFT JOIN to test_point
            offset = (filters.page - 1) * filters.page_size
            query = (
                select(TestCase, TestPoint.name.label('point_name'))
                .join(
                    TestPoint,
                    TestCase.point_id == TestPoint.id,
                    isouter=True  # LEFT JOIN
                )
                .where(and_(*conditions))
                .order_by(TestCase.created_at.desc())
                .offset(offset)
                .limit(filters.page_size)
            )

            result = await self.db.execute(query)
            rows = result.all()

            # Convert to response format
            items = []
            for case, point_name in rows:
                items.append(
                    CaseResponse(
                        id=str(case.id),
                        project_id=str(case.project_id),
                        point_id=str(case.point_id) if case.point_id else None,
                        point_name=point_name,
                        name=case.name,
                        priority=case.priority,
                        case_type=case.case_type,
                        automation_status=case.automation_status,
                        expected_result=case.expected_result,
                        is_finalized=case.is_finalized,
                        version=case.version,
                        hallucination_status=case.hallucination_status,
                        review_status=case.review_status,
                        feasibility_level=case.feasibility_level,
                        refinement_report=case.refinement_report,
                        refined_at=case.refined_at.isoformat() if case.refined_at else None,
                        created_by=case.created_by,
                        created_at=case.created_at.isoformat() if case.created_at else "",
                        updated_at=case.updated_at.isoformat() if case.updated_at else "",
                    )
                )

            return CaseListResponse(
                total=total,
                page=filters.page,
                page_size=filters.page_size,
                items=items,
            )

        except Exception as e:
            logger.error(f"Error listing test cases: {str(e)}")
            raise

    async def get_case_detail(self, case_id: str) -> Optional[CaseDetailResponse]:
        """
        Get detailed information for a single test case

        Args:
            case_id: Test case ID

        Returns:
            CaseDetailResponse or None if not found
        """
        try:
            query = select(TestCase).where(
                and_(
                    TestCase.id == UUID(case_id),
                    TestCase.is_deleted.is_(False)
                )
            )

            result = await self.db.execute(query)
            case = result.scalar_one_or_none()

            if not case:
                return None

            return self._to_detail(case)

        except Exception as e:
            logger.error(f"Error getting test case detail: {str(e)}")
            raise

    async def create_case(self, request: CaseCreateRequest) -> CaseDetailResponse:
        """
        Create a new test case

        Args:
            request: Test case creation request

        Returns:
            Created test case detail
        """
        try:
            # Convert steps to JSON format
            steps_json = [step.model_dump() for step in request.steps]

            # Create new test case
            new_case = TestCase(
                project_id=UUID(request.project_id),
                point_id=UUID(request.point_id) if request.point_id else None,
                name=request.name,
                priority=request.priority,
                case_type=request.case_type,
                automation_status=request.automation_status,
                precondition=request.precondition,
                steps=steps_json,
                expected_result=request.expected_result,
                created_by=request.created_by,
                is_finalized=False,
                version=1,
                hallucination_status="normal",
            )

            self.db.add(new_case)
            await self.db.commit()
            await self.db.refresh(new_case)

            logger.info(f"Created test case: {new_case.id}")

            return self._to_detail(new_case)

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating test case: {str(e)}")
            raise

    async def update_case(self, case_id: str, request: CaseUpdateRequest) -> Optional[CaseDetailResponse]:
        """
        Update an existing test case

        Args:
            case_id: Test case ID
            request: Test case update request

        Returns:
            Updated test case detail or None if not found
        """
        try:
            # Fetch existing case
            query = select(TestCase).where(
                and_(
                    TestCase.id == UUID(case_id),
                    TestCase.is_deleted.is_(False)
                )
            )

            result = await self.db.execute(query)
            case = result.scalar_one_or_none()

            if not case:
                return None

            # Check if case is finalized (cannot update finalized cases unless unfinalizing)
            if case.is_finalized and request.is_finalized is not False:
                logger.warning(f"Attempted to update finalized case: {case_id}")
                raise ValueError("Cannot update finalized test case")

            # W3: snapshot pre-change state before applying updates
            old_snapshot = self._snapshot_dict(case)

            # Update fields if provided
            if request.point_id is not None:
                case.point_id = UUID(request.point_id) if request.point_id else None

            if request.name is not None:
                case.name = request.name

            if request.priority is not None:
                case.priority = request.priority

            if request.case_type is not None:
                case.case_type = request.case_type

            if request.automation_status is not None:
                case.automation_status = request.automation_status

            if request.precondition is not None:
                case.precondition = request.precondition

            if request.steps is not None:
                case.steps = [step.model_dump() for step in request.steps]
                case.version += 1  # Increment version when steps change

            if request.expected_result is not None:
                case.expected_result = request.expected_result

            if request.is_finalized is not None:
                case.is_finalized = request.is_finalized

            if request.hallucination_status is not None:
                case.hallucination_status = request.hallucination_status

            # W5: review & refinement fields
            if request.review_status is not None:
                case.review_status = request.review_status
            if request.review_comment is not None:
                case.review_comment = request.review_comment
            if request.feasibility_level is not None:
                case.feasibility_level = request.feasibility_level
            if request.cannot_automate_reason is not None:
                case.cannot_automate_reason = request.cannot_automate_reason

            # W3: write snapshot of pre-change state with diff summary
            new_snapshot = self._snapshot_dict(case)
            try:
                version = CaseVersion(
                    case_id=case.id,
                    version=case.version if request.steps is None else case.version - 1,
                    snapshot=old_snapshot,
                    diff_summary=self._diff_summary(old_snapshot, new_snapshot),
                    changed_by=getattr(case, "created_by", None) or "system",
                )
                self.db.add(version)
            except Exception as e:
                logger.warning(f"Version snapshot failed (non-blocking): {e}")

            await self.db.commit()
            await self.db.refresh(case)

            logger.info(f"Updated test case: {case_id}")

            return self._to_detail(case)

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating test case: {str(e)}")
            raise

    async def list_versions(self, case_id: str) -> list:
        q = select(CaseVersion).where(
            CaseVersion.case_id == UUID(case_id)
        ).order_by(CaseVersion.version.desc())
        result = await self.db.execute(q)
        return result.scalars().all()

    async def get_version(self, case_id: str, version: int) -> Optional[CaseVersion]:
        q = select(CaseVersion).where(
            CaseVersion.case_id == UUID(case_id),
            CaseVersion.version == version
        ).order_by(CaseVersion.created_at.desc())
        return (await self.db.execute(q)).scalar_one_or_none()

    async def rollback_case(self, case_id: str, target_version: int) -> Optional[CaseDetailResponse]:
        """Rollback case to a snapshot version. version continues to increment."""
        try:
            # fetch case
            q = select(TestCase).where(
                TestCase.id == UUID(case_id), TestCase.is_deleted.is_(False)
            )
            case = (await self.db.execute(q)).scalar_one_or_none()
            if not case:
                return None

            # fetch target snapshot
            vq = select(CaseVersion).where(
                CaseVersion.case_id == UUID(case_id),
                CaseVersion.version == target_version
            ).order_by(CaseVersion.created_at.desc())
            snap = (await self.db.execute(vq)).scalar_one_or_none()
            if not snap:
                raise ValueError(f"Version {target_version} not found")

            # snapshot current state (rollback action itself)
            old_snapshot = self._snapshot_dict(case)

            # apply snapshot
            for f in self._SNAPSHOT_FIELDS:
                setattr(case, f, snap.snapshot.get(f))
            case.version += 1  # never decrement

            # record rollback as a new version
            self.db.add(CaseVersion(
                case_id=case.id,
                version=case.version,
                snapshot=old_snapshot,
                diff_summary=f"回滚到 v{target_version}",
                changed_by=getattr(case, "created_by", None) or "system",
            ))

            await self.db.commit()
            await self.db.refresh(case)
            return self._to_detail(case)
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Rollback failed: {e}")
            raise

    async def refine_case(self, case_id: str) -> Optional[dict]:
        """Run synchronous E2E refinement, persist the report + feasibility fields.

        Returns the refinement report dict, or None if the case is not found.
        """
        from app.services.case_refiner import CaseRefiner

        try:
            q = select(TestCase).where(
                TestCase.id == UUID(case_id), TestCase.is_deleted.is_(False)
            )
            case = (await self.db.execute(q)).scalar_one_or_none()
            if not case:
                return None

            case_dict = {
                "name": case.name, "priority": case.priority, "case_type": case.case_type,
                "precondition": case.precondition or "", "steps": case.steps or [],
                "expected_result": case.expected_result,
            }
            refiner = CaseRefiner()
            report = refiner.refine_sync(case_dict, page_elements=None)
            # 维度3 异常路径：LLM 分析（失败降级为通用提示，不阻塞）
            try:
                llm_suggestions = await refiner._suggest_exception_paths(case_dict)
                report["suggestions"] = (report.get("suggestions") or []) + llm_suggestions
                # 建议增加会拉低评分，重算
                report["score"] = refiner._calculate_score(
                    report["suggestions"], report.get("normativity", {})
                )
            except Exception as llm_err:
                logger.warning(f"LLM exception-path merge failed (non-blocking): {llm_err}")
            case.refinement_report = report
            case.feasibility_level = report.get("feasibility_level")
            case.cannot_automate_reason = report.get("cannot_automate_reason")
            case.refined_at = datetime.utcnow()
            await self.db.commit()
            return report
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Refine failed: {e}")
            raise

    async def apply_suggestions(self, case_id: str, suggestion_ids=None) -> Optional[CaseDetailResponse]:
        """Apply refinement suggestions (all, or by id) and persist updated steps.

        Returns the updated case detail, or None if the case / report is missing.
        """
        try:
            q = select(TestCase).where(
                TestCase.id == UUID(case_id), TestCase.is_deleted.is_(False)
            )
            case = (await self.db.execute(q)).scalar_one_or_none()
            if not case or not case.refinement_report:
                return None

            report = case.refinement_report
            refined = report.get("refined_case") or {}
            # apply refined steps if present
            if "steps" in refined:
                case.steps = refined["steps"]
                case.version += 1
            # 规则层建议自动落地（如"缺前置条件"→ 填充 refined 的 precondition；
            # 软断言转硬断言 → LLM 生成硬断言文案）。此处只做结构性建议：
            # refined_case 里有比 case 更完整的字段时同步过来
            if refined.get("precondition") and not case.precondition:
                case.precondition = refined["precondition"]
            # mark suggestions applied (all pending, or only the specified ids)
            for s in report.get("suggestions", []):
                if suggestion_ids is None or s.get("id") in suggestion_ids:
                    s["status"] = "applied"
            case.refinement_report = report
            await self.db.commit()
            await self.db.refresh(case)
            return self._to_detail(case)
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Apply suggestions failed: {e}")
            raise

    async def delete_case(self, case_id: str) -> bool:
        try:
            query = select(TestCase).where(
                and_(
                    TestCase.id == UUID(case_id),
                    TestCase.is_deleted.is_(False)
                )
            )

            result = await self.db.execute(query)
            case = result.scalar_one_or_none()

            if not case:
                return False

            case.is_deleted = True
            await self.db.commit()

            logger.info(f"Deleted test case: {case_id}")
            return True

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting test case: {str(e)}")
            raise

    async def batch_operation(self, request: BatchOperationRequest) -> Dict[str, Any]:
        """
        Perform batch operations on multiple test cases

        Args:
            request: Batch operation request with case IDs and action

        Returns:
            Result summary with success/failure counts
        """
        try:
            case_ids = [UUID(case_id) for case_id in request.case_ids]
            success_count = 0
            failure_count = 0
            errors = []

            # Fetch all cases
            query = select(TestCase).where(
                and_(
                    TestCase.id.in_(case_ids),
                    TestCase.is_deleted.is_(False)
                )
            )
            result = await self.db.execute(query)
            cases = result.scalars().all()

            if not cases:
                return {
                    "success_count": 0,
                    "failure_count": len(request.case_ids),
                    "errors": ["No valid cases found"],
                }

            # Perform action based on operation type
            if request.action == "delete":
                for case in cases:
                    try:
                        case.is_deleted = True
                        success_count += 1
                    except Exception as e:
                        failure_count += 1
                        errors.append(f"Case {case.id}: {str(e)}")

            elif request.action == "finalize":
                for case in cases:
                    try:
                        case.is_finalized = True
                        success_count += 1
                    except Exception as e:
                        failure_count += 1
                        errors.append(f"Case {case.id}: {str(e)}")

            elif request.action == "unfinalize":
                for case in cases:
                    try:
                        case.is_finalized = False
                        success_count += 1
                    except Exception as e:
                        failure_count += 1
                        errors.append(f"Case {case.id}: {str(e)}")

            elif request.action == "update_priority":
                priority = request.params.get("priority")
                for case in cases:
                    try:
                        case.priority = priority
                        success_count += 1
                    except Exception as e:
                        failure_count += 1
                        errors.append(f"Case {case.id}: {str(e)}")

            elif request.action == "update_automation_status":
                automation_status = request.params.get("automation_status")
                for case in cases:
                    try:
                        case.automation_status = automation_status
                        success_count += 1
                    except Exception as e:
                        failure_count += 1
                        errors.append(f"Case {case.id}: {str(e)}")

            elif request.action == "mark_hallucination":
                hallucination_status = request.params.get("hallucination_status")
                for case in cases:
                    try:
                        case.hallucination_status = hallucination_status
                        success_count += 1
                    except Exception as e:
                        failure_count += 1
                        errors.append(f"Case {case.id}: {str(e)}")

            await self.db.commit()

            logger.info(
                f"Batch operation '{request.action}' completed: "
                f"{success_count} success, {failure_count} failures"
            )

            return {
                "success_count": success_count,
                "failure_count": failure_count,
                "errors": errors,
            }

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error in batch operation: {str(e)}")
            raise

    async def get_stats(self, project_id: str) -> CaseStatsResponse:
        """
        Get statistics for test cases in a project

        Args:
            project_id: Project ID

        Returns:
            CaseStatsResponse with various statistics
        """
        try:
            base_condition = and_(
                TestCase.project_id == UUID(project_id),
                TestCase.is_deleted.is_(False)
            )

            # Total cases count
            total_query = select(func.count()).select_from(TestCase).where(base_condition)
            total_result = await self.db.execute(total_query)
            total_cases = total_result.scalar() or 0

            # Count by priority
            priority_query = (
                select(TestCase.priority, func.count())
                .where(base_condition)
                .group_by(TestCase.priority)
            )
            priority_result = await self.db.execute(priority_query)
            by_priority = {row[0]: row[1] for row in priority_result.all()}

            # Count by case type
            case_type_query = (
                select(TestCase.case_type, func.count())
                .where(base_condition)
                .group_by(TestCase.case_type)
            )
            case_type_result = await self.db.execute(case_type_query)
            by_case_type = {row[0]: row[1] for row in case_type_result.all()}

            # Count by automation status
            automation_query = (
                select(TestCase.automation_status, func.count())
                .where(base_condition)
                .group_by(TestCase.automation_status)
            )
            automation_result = await self.db.execute(automation_query)
            by_automation_status = {row[0]: row[1] for row in automation_result.all()}

            # Finalized count
            finalized_query = (
                select(func.count())
                .select_from(TestCase)
                .where(and_(base_condition, TestCase.is_finalized.is_(True)))
            )
            finalized_result = await self.db.execute(finalized_query)
            finalized_count = finalized_result.scalar() or 0

            # Hallucination count (suspected or confirmed)
            hallucination_query = (
                select(func.count())
                .select_from(TestCase)
                .where(
                    and_(
                        base_condition,
                        TestCase.hallucination_status.in_(["suspected", "confirmed"])
                    )
                )
            )
            hallucination_result = await self.db.execute(hallucination_query)
            hallucination_count = hallucination_result.scalar() or 0

            return CaseStatsResponse(
                total_cases=total_cases,
                by_priority=by_priority,
                by_case_type=by_case_type,
                by_automation_status=by_automation_status,
                finalized_count=finalized_count,
                hallucination_count=hallucination_count,
            )

        except Exception as e:
            logger.error(f"Error getting test case stats: {str(e)}")
            raise


# Singleton instance
def get_test_case_service(db: AsyncSession) -> TestCaseService:
    """
    Factory function to get test case service instance

    Args:
        db: Async database session

    Returns:
        TestCaseService instance
    """
    return TestCaseService(db)


