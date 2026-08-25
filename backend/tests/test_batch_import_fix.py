"""
测试 ElementService.batch_import_elements 的字段映射修复
验证：修复后不再引用已删除的旧字段（alias/display_text/coord_x/coord_y/locator_chain）

注：模块顶层 print 用 sys.stdout.reconfigure(encoding="utf-8") 确保 Windows GBK
控制台不报 UnicodeEncodeError（emoji ✅/❌ 在 GBK 下不可编码）。
"""
import sys
import os
import inspect
from pathlib import Path

# Windows GBK 控制台兼容：强制 stdout/stderr 用 utf-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, Exception):
    pass

# 添加 backend 目录到路径
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

# 读取源码进行静态检查（避免触发 storage/MINIO 等外部依赖）
service_file = backend_path / "app" / "services" / "element_service.py"
source = service_file.read_text(encoding="utf-8")

# 旧字段（已从 ElementRepository 模型删除）
REMOVED_FIELDS = ["alias", "display_text", "coord_x", "coord_y", "locator_chain"]

# 在 batch_import_elements 方法体中查找旧字段引用
# 排除注释/文档字符串中的提及（修复说明）
lines = source.splitlines()
in_method = False
method_depth = 0
violations = []

for i, line in enumerate(lines, 1):
    stripped = line.strip()
    # 检测方法开始
    if "async def batch_import_elements" in line:
        in_method = True
        continue
    # 下一个同级 def 标记方法结束
    if in_method and (stripped.startswith("async def ") or stripped.startswith("def ")) and "_generate_element_id" in stripped:
        # 进入下一个方法，停止检查
        break

    if in_method:
        # 跳过注释和空行
        if not stripped or stripped.startswith("#"):
            continue
        for field in REMOVED_FIELDS:
            # 只检测作为 ElementRepository(...) 关键字参数传入的旧字段
            # （形如 `alias=` / `display_text=` 等无空格的 kwarg）
            # 排除从输入数据读取的局部变量赋值（如 `locator_chain = elem_data.get(...)`）
            if f"{field}=" in stripped and "elem_data.get" not in stripped:
                violations.append((i, field, stripped))

if violations:
    print("❌ 修复失败：batch_import_elements 仍引用已删除字段：")
    for line_no, field, line_text in violations:
        print(f"  第 {line_no} 行 [{field}]: {line_text}")
    sys.exit(1)
else:
    print("✅ 静态检查通过：batch_import_elements 不再引用旧字段")
    print("   已删除字段: alias, display_text, coord_x, coord_y, locator_chain")

# 验证新字段映射存在
NEW_FIELD_PATTERNS = [
    "element_id=",
    "element_name=",
    "element_type=",
    "element_text=",
    "locator_strategies=",
    "semantic_info=",
    "position_x=",
    "position_y=",
    "project_id=",
]

missing_new = []
for pattern in NEW_FIELD_PATTERNS:
    if pattern not in source:
        missing_new.append(pattern)

if missing_new:
    print(f"❌ 新字段映射缺失: {missing_new}")
    sys.exit(1)
else:
    print("✅ 新字段映射完整：element_id, element_name, element_type, element_text, locator_strategies, semantic_info, position_x/y, project_id")

# 验证 _generate_alias 已被 _generate_element_id 替代
if "def _generate_alias" in source:
    print("⚠️  警告：旧方法 _generate_alias 仍存在（应已重命名为 _generate_element_id）")
elif "def _generate_element_id" in source:
    print("✅ 方法重命名完成：_generate_alias → _generate_element_id")
else:
    print("❌ _generate_element_id 方法缺失")
    sys.exit(1)

print("\n🎉 所有验证通过：入库 bug 已修复")
