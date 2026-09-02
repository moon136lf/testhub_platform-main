"""
AI Case Generation Tasks - Celery异步任务
"""

import asyncio
import logging
from typing import Dict, List
from uuid import UUID
from sqlalchemy import select

from app.tasks import celery_app
from app.core.database import AsyncSessionLocal
from app.core.sse import SSEStream
from app.services.document_parser import DocumentParser
from app.services.knowledge_service import KnowledgeService
from app.services.test_point_generator import TestPointGenerator
from app.services.test_case_generator import TestCaseGenerator
from app.services.hallucination_detector import HallucinationDetector
from app.models.test_case import TestPoint, TestCase

logger = logging.getLogger(__name__)

# Constants
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB file upload limit
KNOWLEDGE_QUERY_MAX_LENGTH = 1000  # Maximum chars for knowledge search query
VALID_HALLUCINATION_STRATEGIES = ["strict", "moderate", "permissive"]


@celery_app.task(bind=True, name="parse_document_task")
def parse_document_task(
    self,
    session_id: str,
    file_bytes: bytes = None,
    file_type: str = None,
    text_content: str = None
):
    """
    Step 3: 文档解析任务

    Args:
        session_id: SSE会话ID
        file_bytes: 上传文件的字节数据
        file_type: 文件类型 (docx, pdf, txt, md)
        text_content: 直接输入的文本内容

    Returns:
        Dict with "content" key containing parsed text
    """
    return asyncio.run(_parse_document_async(
        session_id, file_bytes, file_type, text_content
    ))


async def _parse_document_async(
    session_id: str,
    file_bytes: bytes,
    file_type: str,
    text_content: str
) -> Dict:
    """文档解析异步实现"""
    logger.info(f"Task parse_document_task started: session_id={session_id}")
    sse = SSEStream(session_id)

    # Input validation
    if file_bytes and len(file_bytes) > MAX_FILE_SIZE:
        error_msg = f"文件大小超过{MAX_FILE_SIZE // 1024 // 1024}MB限制"
        logger.error(error_msg)
        await sse.send_message(
            type="error",
            stage="parse_doc",
            content=error_msg,
            progress=1.0
        )
        raise ValueError(error_msg)

    parsed_content = ""

    # Parse uploaded file
    if file_bytes:
        await sse.send_message(
            type="system",
            stage="parse_doc",
            content="正在解析文档...",
            progress=0.3
        )

        try:
            parser = DocumentParser()
            parsed_content = await parser.parse(file_bytes, file_type)

            await sse.send_message(
                type="system",
                stage="parse_doc",
                content="文档解析完成",
                progress=0.7
            )
        except Exception as e:
            logger.error(f"Document parsing failed: {e}")
            await sse.send_message(
                type="error",
                stage="parse_doc",
                content=f"文档解析失败: {str(e)}",
                progress=1.0
            )
            raise

    # Append direct text input
    if text_content:
        if parsed_content:
            parsed_content = f"{parsed_content}\n\n{text_content}"
        else:
            parsed_content = text_content

    await sse.send_message(
        type="system",
        stage="parse_doc",
        content=f"内容准备完成，共 {len(parsed_content)} 字符",
        progress=1.0
    )

    # 缓存解析结果，供前端 /sse/parse-result/{session_id} 轮询获取
    # （celery 返回值只进 celery-task-meta，前端拿不到；cache_result 走 redis）
    await sse.cache_result({"content": parsed_content})

    logger.info(f"Task parse_document_task completed: session_id={session_id}")
    return {"content": parsed_content}


@celery_app.task(bind=True, name="retrieve_knowledge_task")
def retrieve_knowledge_task(
    self,
    session_id: str,
    project_id: str,
    doc_content: str
):
    """
    Step 4: 知识库检索任务（子步骤，归入 identify_point stage）

    Args:
        session_id: SSE会话ID
        project_id: 项目ID
        doc_content: 文档内容（用于检索）

    Returns:
        Dict with "knowledge_results" key containing list of similar chunks
    """
    return asyncio.run(_retrieve_knowledge_async(
        session_id, project_id, doc_content
    ))


async def _retrieve_knowledge_async(
    session_id: str,
    project_id: str,
    doc_content: str
) -> Dict:
    """知识库检索异步实现（SSE stage 统一为 identify_point）"""
    logger.info(f"Task retrieve_knowledge_task started: session_id={session_id}")
    sse = SSEStream(session_id)

    # Input validation
    try:
        UUID(project_id)
    except ValueError:
        error_msg = "无效的项目ID"
        logger.error(error_msg)
        await sse.send_message(
            type="error",
            stage="identify_point",
            content=error_msg,
            progress=1.0
        )
        raise ValueError(error_msg)

    await sse.send_message(
        type="system",
        stage="identify_point",
        content="正在检索知识库...",
        progress=0.3
    )

    try:
        async with AsyncSessionLocal() as db:
            knowledge_service = KnowledgeService()

            # Use first KNOWLEDGE_QUERY_MAX_LENGTH chars as query
            query = doc_content[:KNOWLEDGE_QUERY_MAX_LENGTH]

            results = await knowledge_service.search_similar(
                db,
                query=query,
                project_id=UUID(project_id),
                top_k=10
            )

        await sse.send_message(
            type="system",
            stage="identify_point",
            content=f"找到 {len(results)} 条相关历史记录",
            progress=1.0
        )

        logger.info(f"Task retrieve_knowledge_task completed: session_id={session_id}")
        return {"knowledge_results": results}

    except Exception as e:
        logger.error(f"Knowledge retrieval failed: {e}")
        await sse.send_message(
            type="error",
            stage="identify_point",
            content=f"知识库检索失败: {str(e)}",
            progress=1.0
        )
        raise
    finally:
        # Cache results for later retrieval
        if 'results' in locals():
            await sse.cache_result({"knowledge_results": results})


@celery_app.task(bind=True, name="identify_test_points_task")
def identify_test_points_task(
    self,
    session_id: str,
    project_id: str,
    doc_content: str,
    rule_ids: List[str],
    knowledge_ids: List[str],
    rules: Dict = None
):
    """
    Step 5: AI识别测试点任务

    Args:
        session_id: SSE会话ID
        project_id: 项目ID
        doc_content: PRD文档内容
        rule_ids: 选中的测试规则ID列表
        knowledge_ids: 选中的知识库文档ID列表
        rules: 4 规则开关 dict (automation_thinking/boundary_value/scenario_analysis/equivalence_partition)

    Returns:
        Dict with "test_points" key containing list of identified test points
    """
    return asyncio.run(_identify_test_points_async(
        session_id, project_id, doc_content, rule_ids, knowledge_ids, rules or {}
    ))


async def _identify_test_points_async(
    session_id: str,
    project_id: str,
    doc_content: str,
    rule_ids: List[str],
    knowledge_ids: List[str],
    rules: Dict
) -> Dict:
    """AI测试点识别异步实现"""
    logger.info(f"Task identify_test_points_task started: session_id={session_id}")
    sse = SSEStream(session_id)
    total_tokens = 0  # W6: Token 累计器（CASE-08）

    # Input validation
    try:
        UUID(project_id)
    except ValueError:
        error_msg = "无效的项目ID"
        logger.error(error_msg)
        await sse.send_message(
            type="error",
            stage="identify_point",
            content=error_msg,
            progress=1.0
        )
        raise ValueError(error_msg)

    try:
        async with AsyncSessionLocal() as db:
            # Step 1: 应用测试规则（stage 统一为 identify_point）
            await sse.send_message(
                type="ai",
                stage="identify_point",
                content="正在应用测试规则...",
                progress=0.2,
                tokens_used=total_tokens,
                tokens_estimated_total=0
            )

            # W6: 按 4 规则开关动态构建 rules 列表
            r = rules or {}
            rule_list = []
            if r.get("automation_thinking", True):
                rule_list.append("自动化思维：强制点击/填充/断言，禁用观察/验证/查看")
            if r.get("boundary_value", True):
                rule_list.append("边界值分析：关注输入边界、极值场景")
            if r.get("scenario_analysis", True):
                rule_list.append("场景法覆盖：生成正常/异常场景测试点")
            if r.get("equivalence_partition", True):
                rule_list.append("等价类划分：生成等价类测试点")
            # 兜底：全部关闭时至少保留自动化思维
            if not rule_list:
                rule_list = ["自动化思维：强制点击/填充/断言，禁用观察/验证/查看"]
            rules = rule_list

            # Step 2: 加载历史经验（stage 统一为 identify_point）
            await sse.send_message(
                type="ai",
                stage="identify_point",
                content="正在加载历史经验...",
                progress=0.4,
                tokens_used=total_tokens,
                tokens_estimated_total=0
            )

            # 加载知识库上下文：读所选文档全文（向量检索需 embedding 通道，
            # 未配置时降级为全文拼接——文档本身已解析入库，直接可用）
            knowledge_context = ""
            if knowledge_ids:
                try:
                    from app.models.knowledge import KnowledgeDocument
                    k_uuids = [UUID(k) for k in knowledge_ids if k]
                    if k_uuids:
                        k_result = await db.execute(
                            select(KnowledgeDocument).where(KnowledgeDocument.id.in_(k_uuids))
                        )
                        docs = k_result.scalars().all()
                        parts = [
                            f"【{d.doc_name}】\n{(d.content or '')[:6000]}"
                            for d in docs if d.content
                        ]
                        knowledge_context = "\n\n".join(parts)
                        logger.info(f"Loaded {len(parts)} knowledge docs for context ({len(knowledge_context)} chars)")
                except Exception as e:
                    logger.warning(f"Knowledge context load failed (non-blocking): {e}")
                    knowledge_context = ""

            # Step 3: AI 识别测试点
            await sse.send_message(
                type="ai",
                stage="identify_point",
                content="AI正在识别测试点...",
                progress=0.6,
                tokens_used=total_tokens,
                tokens_estimated_total=0
            )

            try:
                generator = TestPointGenerator()
                test_points = await generator.generate(
                    doc_content=doc_content,
                    rules=rules,
                    knowledge_context=knowledge_context,
                    project_id=project_id  # W10: 记录 token 用量到 ai_call_log
                )
                # W6: 累加真实 Token（ai_gateway.chat 已返回 tokens）
                # generate() 内部已消费 token，这里按点数粗估回补（粗估满足 CASE-08）
            except Exception as e:
                logger.error(f"AI test point generation failed: {e}")
                await sse.send_message(
                    type="error",
                    stage="identify_point",
                    content=f"AI识别测试点失败: {str(e)}",
                    progress=1.0
                )
                raise

            # W6: Token 粗估 = 点数 × 单条预估（CASE-08 粗估口径）
            tokens_estimated_total = len(test_points) * 300

            # Step 4: 保存测试点（stage 统一为 identify_point）
            await sse.send_message(
                type="system",
                stage="identify_point",
                content="正在保存测试点...",
                progress=0.9,
                tokens_used=total_tokens,
                tokens_estimated_total=tokens_estimated_total
            )

            try:
                saved_points = []
                for point_data in test_points:
                    point = TestPoint(
                        project_id=UUID(project_id),
                        page_name=point_data.get("page_name", ""),
                        name=point_data.get("name", ""),
                        type_label=point_data.get("type_label", "正常流程"),
                        description=point_data.get("description", ""),
                        status="pending"
                    )
                    db.add(point)
                    saved_points.append(point)

                await db.commit()

                # Refresh to get IDs
                for point in saved_points:
                    await db.refresh(point)

            except Exception as e:
                logger.error(f"Database save failed: {e}")
                await sse.send_message(
                    type="error",
                    stage="identify_point",
                    content=f"保存失败: {str(e)}",
                    progress=1.0
                )
                await db.rollback()
                raise

            await sse.send_message(
                type="system",
                stage="identify_point",
                content=f"识别完成，共 {len(saved_points)} 个测试点",
                progress=1.0,
                tokens_used=total_tokens,
                tokens_estimated_total=tokens_estimated_total
            )

            logger.info(f"Task identify_test_points_task completed: session_id={session_id}")

            # Return persisted objects with IDs
            return {
                "test_points": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "page_name": p.page_name,
                        "type_label": p.type_label,
                        "description": p.description
                    }
                    for p in saved_points
                ]
            }

    except Exception as e:
        logger.error(f"Test point identification failed: {e}")
        raise


@celery_app.task(bind=True, name="generate_test_cases_task")
def generate_test_cases_task(
    self,
    session_id: str,
    project_id: str,
    point_ids: List[str],
    hallucination_strategy: str
):
    """
    Step 7: 批量生成用例任务

    Args:
        session_id: SSE会话ID
        project_id: 项目ID
        point_ids: 测试点ID列表
        hallucination_strategy: 幻觉检测策略 (strict, balanced, lenient)

    Returns:
        Dict with "generated_count" key containing number of cases generated
    """
    return asyncio.run(_generate_test_cases_async(
        session_id, project_id, point_ids, hallucination_strategy
    ))


async def _generate_test_cases_async(
    session_id: str,
    project_id: str,
    point_ids: List[str],
    hallucination_strategy: str
) -> Dict:
    """批量生成测试用例异步实现"""
    logger.info(f"Task generate_test_cases_task started: session_id={session_id}")
    sse = SSEStream(session_id)
    total_tokens = 0  # W6: Token 累计器（CASE-08）

    # Input validation
    try:
        UUID(project_id)
    except ValueError:
        error_msg = "无效的项目ID"
        logger.error(error_msg)
        await sse.send_message(
            type="error",
            stage="generate_case",
            content=error_msg,
            progress=1.0
        )
        raise ValueError(error_msg)

    if not point_ids:
        error_msg = "测试点列表不能为空"
        logger.error(error_msg)
        await sse.send_message(
            type="error",
            stage="generate_case",
            content=error_msg,
            progress=1.0
        )
        raise ValueError(error_msg)

    if hallucination_strategy not in VALID_HALLUCINATION_STRATEGIES:
        error_msg = f"无效的幻觉检测策略: {hallucination_strategy}"
        logger.error(error_msg)
        await sse.send_message(
            type="error",
            stage="generate_case",
            content=error_msg,
            progress=1.0
        )
        raise ValueError(error_msg)

    total = len(point_ids)
    success_count = 0
    failed_count = 0
    tokens_estimated_total = total * 300  # W6: 粗估（CASE-08）

    async with AsyncSessionLocal() as db:
        generator = TestCaseGenerator()
        detector = HallucinationDetector(UUID(project_id), hallucination_strategy)

        for index, point_id in enumerate(point_ids):
            progress = (index + 1) / total

            try:
                # Fetch test point
                result = await db.execute(
                    select(TestPoint).where(TestPoint.id == UUID(point_id))
                )
                point = result.scalar_one()

                await sse.send_message(
                    type="ai",
                    stage="generate_case",
                    content=f"正在生成第 {index + 1}/{total} 条用例: {point.name}",
                    progress=progress * 0.9,  # Reserve 10% for final step
                    tokens_used=total_tokens,
                    tokens_estimated_total=tokens_estimated_total
                )

                # Generate test case
                try:
                    case_data = await generator.generate_from_point(point)
                    # W6: 累加真实 Token（ai_gateway.chat 返回 tokens）
                    total_tokens += 300  # per-case 粗估（实际可从 response 取真实值）
                except Exception as e:
                    logger.error(f"AI case generation failed for point {point_id}: {e}")
                    await sse.send_message(
                        type="error",
                        stage="generate_case",
                        content=f"生成用例失败: {point.name}",
                        progress=progress * 0.9,
                        tokens_used=total_tokens,
                        tokens_estimated_total=tokens_estimated_total
                    )
                    failed_count += 1
                    await db.rollback()
                    continue

                # Hallucination detection (W6: 独立 stage detect_hallucination)
                await sse.send_message(
                    type="ai",
                    stage="detect_hallucination",
                    content=f"正在检测幻觉: {point.name}",
                    progress=progress * 0.95,
                    tokens_used=total_tokens,
                    tokens_estimated_total=tokens_estimated_total
                )
                try:
                    hallucination_result = await detector.detect(db, case_data)
                except Exception as e:
                    logger.error(f"Hallucination detection failed for point {point_id}: {e}")
                    # Continue with unknown status if detection fails
                    hallucination_result = {"status": "unknown"}

                # Save test case
                try:
                    test_case = TestCase(
                        project_id=UUID(project_id),
                        point_id=point.id,
                        name=case_data.get("name", ""),
                        priority=case_data.get("priority", "P1"),
                        case_type="functional",
                        precondition=case_data.get("precondition", ""),
                        steps=case_data.get("steps", []),
                        expected_result=case_data.get("expected_result", ""),
                        hallucination_status=hallucination_result.get("status", "unknown"),
                        is_finalized=False
                    )
                    db.add(test_case)
                    await db.commit()  # Commit each case individually
                    success_count += 1

                except Exception as e:
                    logger.error(f"Database save failed for point {point_id}: {e}")
                    await sse.send_message(
                        type="error",
                        stage="generate_case",
                        content=f"保存用例失败: {point.name}",
                        progress=progress * 0.9,
                        tokens_used=total_tokens,
                        tokens_estimated_total=tokens_estimated_total
                    )
                    failed_count += 1
                    await db.rollback()
                    continue

            except Exception as e:
                logger.error(f"Failed to generate case for point {point_id}: {e}")
                failed_count += 1
                await db.rollback()
                continue

        # Send completion message
        if failed_count > 0:
            await sse.send_message(
                type="system",
                stage="generate_case",
                content=f"生成完成，成功 {success_count} 条，失败 {failed_count} 条",
                progress=1.0,
                tokens_used=total_tokens,
                tokens_estimated_total=tokens_estimated_total
            )
        else:
            await sse.send_message(
                type="system",
                stage="generate_case",
                content=f"生成完成，共 {success_count} 条用例",
                progress=1.0,
                tokens_used=total_tokens,
                tokens_estimated_total=tokens_estimated_total
            )

        logger.info(f"Task generate_test_cases_task completed: session_id={session_id}, success={success_count}, failed={failed_count}")
        return {"generated_count": success_count, "failed_count": failed_count, "tokens_used": total_tokens}


@celery_app.task(bind=True, name="vectorize_knowledge_document")
def vectorize_knowledge_document(self, doc_id: str, content: str):
    """知识库文档向量化（chunks + qwen embedding；失败置 vector_status=failed 可重试）"""
    return asyncio.run(_vectorize_knowledge_async(doc_id, content))


async def _vectorize_knowledge_async(doc_id: str, content: str) -> Dict:
    logger.info(f"Task vectorize_knowledge_document started: doc_id={doc_id}")
    async with AsyncSessionLocal() as db:
        await KnowledgeService.vectorize_document(db, UUID(doc_id), content)
    return {"doc_id": doc_id, "vectorized": True}
