"""
Document Parser Service Tests
"""

import pytest
from app.services.document_parser import DocumentParser


class TestDocumentParser:
    """测试文档解析服务"""

    @pytest.fixture
    def parser(self):
        """创建 DocumentParser 实例"""
        return DocumentParser()

    @pytest.mark.asyncio
    async def test_parse_txt_utf8(self, parser):
        """测试解析 UTF-8 编码的 TXT 文件"""
        content = "这是一个测试文档\n包含中文内容"
        file_bytes = content.encode('utf-8')

        result = await parser.parse(file_bytes, "txt")

        assert result == content
        assert "测试文档" in result
        assert "中文内容" in result

    @pytest.mark.asyncio
    async def test_parse_txt_gbk(self, parser):
        """测试解析 GBK 编码的 TXT 文件"""
        content = "这是GBK编码的文档\n测试内容"
        file_bytes = content.encode('gbk')

        result = await parser.parse(file_bytes, "txt")

        assert result == content
        assert "GBK编码" in result

    @pytest.mark.asyncio
    async def test_parse_markdown(self, parser):
        """测试解析 Markdown 文件"""
        markdown_content = """# 测试标题

这是一段**加粗文本**和*斜体文本*。

## 二级标题

- 列表项 1
- 列表项 2

[链接](https://example.com)
"""
        file_bytes = markdown_content.encode('utf-8')

        result = await parser.parse(file_bytes, "md")

        assert "测试标题" in result
        assert "加粗文本" in result
        assert "斜体文本" in result
        assert "列表项 1" in result
        assert "链接" in result
        # HTML tags should be stripped
        assert "<h1>" not in result
        assert "<strong>" not in result
        assert "<em>" not in result

    @pytest.mark.asyncio
    async def test_parse_simple_markdown(self, parser):
        """测试解析简单的 Markdown 文件"""
        markdown_content = "# Hello World\n\nThis is a test."
        file_bytes = markdown_content.encode('utf-8')

        result = await parser.parse(file_bytes, "md")

        assert "Hello World" in result
        assert "This is a test" in result

    @pytest.mark.asyncio
    async def test_parse_unsupported_type(self, parser):
        """测试解析不支持的文件类型"""
        file_bytes = b"test content"

        with pytest.raises(ValueError) as exc_info:
            await parser.parse(file_bytes, "xyz")

        assert "Unsupported file type" in str(exc_info.value)
        assert "xyz" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_parse_empty_txt(self, parser):
        """测试解析空 TXT 文件"""
        file_bytes = b""

        result = await parser.parse(file_bytes, "txt")

        assert result == ""

    @pytest.mark.asyncio
    async def test_parse_txt_with_multiple_encodings(self, parser):
        """测试 TXT 文件编码自动检测"""
        # Test GB2312 encoding
        content = "简体中文测试"
        file_bytes = content.encode('gb2312')

        result = await parser.parse(file_bytes, "txt")

        assert "简体中文" in result

    @pytest.mark.asyncio
    async def test_parse_markdown_with_blank_lines(self, parser):
        """测试 Markdown 解析处理多余空行"""
        markdown_content = """# Title


Paragraph 1


Paragraph 2
"""
        file_bytes = markdown_content.encode('utf-8')

        result = await parser.parse(file_bytes, "md")

        assert "Title" in result
        assert "Paragraph 1" in result
        assert "Paragraph 2" in result
        # Should not have more than 2 consecutive newlines
        assert "\n\n\n" not in result
