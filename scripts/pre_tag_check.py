# -*- coding: utf-8 -*-
"""打 tag 前的验证脚本 (Git 版本管理配套, docs/OPERATIONS.md 第 13 节).

用法: 打 tag 前在项目根目录跑一次, 全部通过再打。
  python scripts/pre_tag_check.py

检查项:
1. 后端全量测试绿 (排除环境依赖用例)
2. 前端 build 过
3. 敏感信息扫描 (真 key 模式)
4. 工作区干净 (无未提交代码)
"""
import io
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
FAILED = []


def run(name, cmd, cwd, allow_fail=False):
    print(f"\n=== {name} ===")
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = (r.stdout or r.stderr).strip().splitlines()[-3:]
    for line in tail:
        print(" ", line)
    if r.returncode != 0 and not allow_fail:
        FAILED.append(name)
        print("  ❌ FAILED")
    else:
        print("  ✅ OK")
    return r


def main():
    print("MoonTest 打 tag 前检查")
    print("=" * 40)

    # 1. 工作区干净 (代码文件; docs 自动存档允许存在)
    r = subprocess.run("git status --short", cwd=ROOT, shell=True,
                       capture_output=True, text=True, encoding="utf-8")
    dirty_code = [l for l in (r.stdout or "").splitlines()
                  if l.strip() and not l.startswith("?? docs/") and "SESSION_ARCHIVE" not in l
                  and not l.strip().startswith("?? backend/.en")]
    if dirty_code:
        FAILED.append("工作区有未提交代码")
        print("\n=== 工作区检查 ===\n  ❌ 未提交:", dirty_code)
    else:
        print("\n=== 工作区检查 ===\n  ✅ OK")

    # 2. 后端测试
    run("后端全量测试",
        "python -m pytest tests/ -q --ignore=tests/test_batch_import_fix.py --deselect tests/test_storage_get_object.py",
        ROOT / "backend")

    # 3. 前端 build
    run("前端 build", "npx vite build", ROOT / "frontend")

    # 4. 敏感信息扫描 (真 key 模式: sk- 后跟 20+ 非占位字符)
    r = subprocess.run(
        'git grep -lE "sk-[a-wyzA-WYZ0-9]{20,}" -- ":!*/test_security.py"',
        cwd=ROOT, shell=True, capture_output=True, text=True, encoding="utf-8")
    # sk-xxxx... 占位符 (全 x) 是测试样例, 排除 x 连串
    hits = [l for l in (r.stdout or "").splitlines() if l.strip()]
    print("\n=== 敏感信息扫描 ===")
    if hits:
        FAILED.append("疑似真 key 入库")
        print("  ❌ 疑似真实 API key:", hits)
    else:
        print("  ✅ OK (无真实 key 模式)")

    print("\n" + "=" * 40)
    if FAILED:
        print(f"❌ 未通过: {FAILED} — 修复后再打 tag")
        sys.exit(1)
    print("✅ 全部通过, 可以打 tag:")
    print('  git tag -a vX.Y.Z -m "版本说明"')


if __name__ == "__main__":
    main()
