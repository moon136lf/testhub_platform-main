"""Import/export service for test cases."""
import json
import csv
import io
import logging
from uuid import UUID
from typing import List

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_case import TestCase
from app.schemas.test_case import CaseCreateRequest, StepSchema

logger = logging.getLogger(__name__)


class ImportExportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- export ----------
    def export_cases(self, project_id: str, fmt: str) -> bytes:
        # NOTE: caller should pre-fetch cases; here we fetch sync-ish via stored list
        raise NotImplementedError  # see export_cases_async

    async def _fetch_cases(self, project_id: str) -> List[TestCase]:
        q = select(TestCase).where(
            TestCase.project_id == UUID(project_id),
            TestCase.is_deleted.is_(False),
        ).order_by(TestCase.created_at.desc())
        result = await self.db.execute(q)
        return result.scalars().all()

    async def export_cases_async(self, project_id: str, fmt: str) -> bytes:
        cases = await self._fetch_cases(project_id)
        if fmt == "json":
            return self._export_json(cases)
        elif fmt == "xlsx":
            return self._export_xlsx(cases)
        elif fmt == "xmind":
            return self._export_xmind(cases)
        raise ValueError(f"Unsupported export format: {fmt}")

    def _case_to_dict(self, case: TestCase) -> dict:
        return {
            "name": case.name, "priority": case.priority,
            "case_type": case.case_type, "automation_status": case.automation_status,
            "precondition": case.precondition or "", "steps": case.steps or [],
            "expected_result": case.expected_result,
        }

    def _export_json(self, cases) -> bytes:
        return json.dumps([self._case_to_dict(c) for c in cases], ensure_ascii=False).encode("utf-8")

    def _export_xlsx(self, cases) -> bytes:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "测试用例"
        ws.append(["用例名", "优先级", "类型", "步骤", "动作", "目标", "数据", "预期(步)", "预期结果"])
        for c in cases:
            for i, s in enumerate(c.steps or [], 1):
                ws.append([c.name, c.priority, c.case_type, i,
                           s.get("action", ""), s.get("target", ""),
                           s.get("data", ""), s.get("expected", ""),
                           c.expected_result])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def _export_xmind(self, cases) -> bytes:
        import xmind
        from xmind.core.topic import TopicElement
        from collections import defaultdict
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".xmind", delete=False) as tf:
            path = tf.name
        try:
            wb = xmind.load(path)
            root = wb.getPrimarySheet().getRootTopic()
            root.setTitle("测试用例")
            groups = defaultdict(list)
            for c in cases:
                groups[c.case_type].append(c)
            for gname, gcases in groups.items():
                gtopic = TopicElement()
                gtopic.setTitle(gname)
                root.addSubTopic(gtopic)
                for c in gcases:
                    ctopic = TopicElement()
                    ctopic.setTitle(c.name)
                    gtopic.addSubTopic(ctopic)
                    for s in c.steps or []:
                        st = TopicElement()
                        st.setTitle(f"{s.get('action','')} -> {s.get('expected','')}")
                        ctopic.addSubTopic(st)
            xmind.save(wb, path)
            with open(path, "rb") as f:
                return f.read()
        finally:
            try: os.unlink(path)
            except OSError: pass

    # ---------- import ----------
    async def import_cases(self, project_id: str, file_bytes: bytes, fmt: str) -> dict:
        rows = self._parse(file_bytes, fmt)
        imported = 0
        failed = 0
        errors = []
        for idx, row in enumerate(rows, start=1):
            try:
                req = CaseCreateRequest(
                    project_id=project_id,
                    name=row["name"],
                    priority=row.get("priority", "P1"),
                    case_type=row.get("case_type", "functional"),
                    steps=row.get("steps") or [{"step":1,"action":"待补","expected":"待补"}],
                    expected_result=row.get("expected_result", ""),
                )
                steps_json = [s if isinstance(s, dict) else s.model_dump() for s in req.steps]
                case = TestCase(
                    project_id=UUID(project_id), name=req.name, priority=req.priority,
                    case_type=req.case_type, automation_status="pending",
                    precondition=req.precondition, steps=steps_json,
                    expected_result=req.expected_result, version=1,
                    hallucination_status="normal", is_finalized=False,
                )
                self.db.add(case)
                await self.db.commit()
                imported += 1
            except IntegrityError:
                await self.db.rollback()
                failed += 1
                errors.append({"row": idx, "reason": f"名称冲突: {row.get('name','')}"})
            except Exception as e:
                await self.db.rollback()
                failed += 1
                errors.append({"row": idx, "reason": str(e)})
        return {"imported": imported, "failed": failed, "errors": errors}

    def _parse(self, file_bytes: bytes, fmt: str) -> List[dict]:
        if fmt == "csv":
            return self._parse_csv(file_bytes)
        elif fmt == "md":
            return self._parse_md(file_bytes)
        elif fmt == "xlsx":
            return self._parse_xlsx(file_bytes)
        raise ValueError(f"Unsupported import format: {fmt}")

    def _parse_csv(self, file_bytes: bytes) -> List[dict]:
        text = file_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for r in reader:
            steps = []
            if r.get("steps"):
                try: steps = json.loads(r["steps"])
                except json.JSONDecodeError: steps = []
            rows.append({
                "name": r.get("name","").strip(),
                "priority": r.get("priority","P1").strip(),
                "case_type": r.get("case_type","functional").strip(),
                "precondition": r.get("precondition","").strip(),
                "steps": steps,
                "expected_result": r.get("expected_result","").strip(),
            })
        return rows

    def _parse_md(self, file_bytes: bytes) -> List[dict]:
        text = file_bytes.decode("utf-8")
        rows = []
        current = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("## "):
                if current: rows.append(current)
                current = {"name": line[3:].strip(), "priority":"P1","case_type":"functional",
                           "precondition":"","steps":[],"expected_result":""}
            elif current is None:
                continue
            elif line.startswith("- 前置:"): current["precondition"] = line[len("- 前置:"):].strip()
            elif line.startswith("- 优先级:"): current["priority"] = line[len("- 优先级:"):].strip()
            elif line.startswith("- 预期:"): current["expected_result"] = line[len("- 预期:"):].strip()
            elif line.startswith("- 步骤:"):
                steps = []
                for s in line[len("- 步骤:"):].split(";"):
                    s = s.strip()
                    if s: steps.append({"step":len(steps)+1,"action":s,"expected":"待补"})
                current["steps"] = steps
        if current: rows.append(current)
        return rows

    def _parse_xlsx(self, file_bytes: bytes) -> List[dict]:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(file_bytes))
        ws = wb.active
        rows = []
        current = None
        for r in ws.iter_rows(min_row=2, values_only=True):
            name, priority, ctype, step_no, action, target, data, expected_step, expected_result = (list(r) + [None]*9)[:9]
            if name:  # new case row
                if current: rows.append(current)
                current = {"name":name,"priority":priority or "P1","case_type":ctype or "functional",
                           "precondition":"","steps":[],"expected_result":expected_result or ""}
            if current and action:
                current["steps"].append({
                    "step": len(current["steps"])+1, "action": action,
                    "target": target or "", "data": data or "", "expected": expected_step or ""
                })
        if current: rows.append(current)
        return rows
