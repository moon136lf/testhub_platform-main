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
    Step 4: 知识库检索任务

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
    """知识库检索异步实现"""
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
            stage="fetch_knowledge",
            content=error_msg,
            progress=1.0
        )
        raise ValueError(error_msg)

    await sse.send_message(
        type="system",
        stage="fetch_knowledge",
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
            stage="fetch_knowledge",
            content=f"找到 {len(results)} 条相关历史记录",
            progress=1.0
        )

        logger.info(f"Task retrieve_knowledge_task completed: session_id={session_id}")
        return {"knowledge_results": results}

    except Exception as e:
        logger.error(f"Knowledge retrieval failed: {e}")
        await sse.send_message(
            type="error",
            stage="fetch_knowledge",
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
    knowledge_ids: List[str]
):
    """
    Step 5: AI识别测试点任务

    Args:
        session_id: SSE会话ID
        project_id: 项目ID
        doc_content: PRD文档内容
        rule_ids: 选中的测试规则ID列表
        knowledge_ids: 选中的知识库文档ID列表

    Returns:
        Dict with "test_points" key containing list of identified test points
    """
    return asyncio.run(_identify_test_points_async(
        session_id, project_id, doc_content, rule_ids, knowledge_ids
    ))


async def _identify_test_points_async(
    session_id: str,
    project_id: str,
    doc_content: str,
    rule_ids: List[str],
    knowledge_ids: List[str]
) -> Dict:
    """AI测试点识别异步实现"""
    logger.info(f"Task identify_test_points_task started: session_id={session_id}")
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

    try:
        async with AsyncSessionLocal() as db:
            # Step 1: Load rules
            await sse.send_message(
                type="ai",
                stage="apply_rules",
                content="正在应用测试规则...",
                progress=0.2
            )

            # TODO: Load actual rules from database when rule table is ready
            rules = [
                "自动化思维：优先识别可自动化的测试点",
                "边界值分析：关注输入边界、极值场景",
                "异常场景：识别异常输入、错误处理场景"
            ]

            # Step 2: Load knowledge context
            await sse.send_message(
                type="ai",
                stage="load_knowledge",
                content="正在加载历史经验...",
                progress=0.4
            )

            # TODO: Load actual knowledge chunks when needed
            knowledge_context = ""
            if knowledge_ids:
                knowledge_context = "参考历史测试经验..."

            # Step 3: Call AI to generate test points
            await sse.send_message(
                type="ai",
                stage="identify_point",
                content="AI正在识别测试点...",
                progress=0.6
            )

            try:
                generator = TestPointGenerator()
                test_points = await generator.generate(
                    doc_content=doc_content,
                    rules=rules,
                    knowledge_context=knowledge_context
                )
            except Exception as e:
                logger.error(f"AI test point generation failed: {e}")
                await sse.send_message(
                    type="error",
                    stage="identify_point",
                    content=f"AI识别测试点失败: {str(e)}",
                    progress=1.0
                )
                raise

            # Step 4: Save to database
            await sse.send_message(
                type="system",
                stage="save_points",
                content="正在保存测试点...",
                progress=0.9
            )

            try:
                saved_points = []
                for point_data in test_points:
                    point = TestPoint(
                        project_id=UUID(project_id),
                        page_name=point_data.get("page_name", ""),
                        name=point_data.get("name", ""),
                        type_label=point_data.get("type_label", "功能"),
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
                    stage="save_points",
                    content=f"保存失败: {str(e)}",
                    progress=1.0
                )
                await db.rollback()
                raise

            await sse.send_message(
                type="system",
                stage="identify_point",
                content=f"识别完成，共 {len(saved_points)} 个测试点",
                progress=1.0
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
                    progress=progress * 0.9  # Reserve 10% for final step
                )

                # Generate test case
                try:
                    case_data = await generator.generate_from_point(point)
                except Exception as e:
                    logger.error(f"AI case generation failed for point {point_id}: {e}")
                    await sse.send_message(
                        type="error",
                        stage="generate_case",
                        content=f"生成用例失败: {point.name}",
                        progress=progress * 0.9
                    )
                    failed_count += 1
                    await db.rollback()
                    continue

                # Hallucination detection
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
                        progress=progress * 0.9
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
                progress=1.0
            )
        else:
            await sse.send_message(
                type="system",
                stage="generate_case",
                content=f"生成完成，共 {success_count} 条用例",
                progress=1.0
            )

        logger.info(f"Task generate_test_cases_task completed: session_id={session_id}, success={success_count}, failed={failed_count}")
        return {"generated_count": success_count, "failed_count": failed_count}
