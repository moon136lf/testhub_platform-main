"""
Document Parser Service

Supports parsing multiple document formats:
- DOCX (Word documents)
- PDF (Portable Document Format)
- TXT (Plain text with encoding detection)
- MD (Markdown)
"""

import logging
import re
from typing import Optional
from io import BytesIO

# Document parsing libraries
from docx import Document
from PyPDF2 import PdfReader
import markdown

logger = logging.getLogger(__name__)


class DocumentParser:
    """文档解析服务，支持多种文件格式"""

    async def parse(self, file_bytes: bytes, file_type: str) -> str:
        """
        解析文档并提取文本内容

        Args:
            file_bytes: 文档的字节数据
            file_type: 文件类型 (docx, pdf, txt, md)

        Returns:
            提取的文本内容

        Raises:
            ValueError: 不支持的文件类型
            Exception: 解析失败
        """
        parsers = {
            "docx": self._parse_docx,
            "pdf": self._parse_pdf,
            "txt": self._parse_txt,
            "md": self._parse_markdown
        }

        if file_type not in parsers:
            raise ValueError(f"Unsupported file type: {file_type}")

        logger.info(f"Parsing {file_type} document, size: {len(file_bytes)} bytes")

        try:
            content = await parsers[file_type](file_bytes)
            logger.info(f"Successfully parsed {file_type} document, extracted {len(content)} characters")
            return content
        except Exception as e:
            logger.error(f"Failed to parse {file_type} document: {e}", exc_info=True)
            raise

    async def _parse_docx(self, file_bytes: bytes) -> str:
        """
        解析 DOCX 文档

        Args:
            file_bytes: DOCX 文档字节数据

        Returns:
            提取的文本内容
        """
        try:
            doc = Document(BytesIO(file_bytes))
            paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
            content = "\n".join(paragraphs)
            logger.info(f"Extracted {len(paragraphs)} paragraphs from DOCX")
            return content
        except Exception as e:
            logger.error(f"DOCX parsing error: {e}")
            raise

    async def _parse_pdf(self, file_bytes: bytes) -> str:
        """
        解析 PDF 文档

        Args:
            file_bytes: PDF 文档字节数据

        Returns:
            提取的文本内容
        """
        try:
            pdf_reader = PdfReader(BytesIO(file_bytes))
            pages = []
            for page_num, page in enumerate(pdf_reader.pages):
                text = page.extract_text()
                if text.strip():
                    pages.append(text)

            content = "\n".join(pages)
            logger.info(f"Extracted text from {len(pdf_reader.pages)} pages")
            return content
        except Exception as e:
            logger.error(f"PDF parsing error: {e}")
            raise

    async def _parse_txt(self, file_bytes: bytes) -> str:
        """
        解析 TXT 文档，支持多种编码自动检测

        尝试的编码顺序: utf-8, gbk, gb2312, utf-16

        Args:
            file_bytes: TXT 文档字节数据

        Returns:
            提取的文本内容
        """
        encodings = ['utf-8', 'gbk', 'gb2312', 'utf-16']

        for encoding in encodings:
            try:
                content = file_bytes.decode(encoding)
                logger.info(f"Successfully decoded TXT with {encoding} encoding")
                return content
            except (UnicodeDecodeError, LookupError):
                continue

        # If all encodings fail, raise an exception
        error_msg = f"Failed to decode TXT file with any of these encodings: {', '.join(encodings)}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    async def _parse_markdown(self, file_bytes: bytes) -> str:
        """
        解析 Markdown 文档

        将 Markdown 转换为 HTML，然后剥离 HTML 标签提取纯文本

        Args:
            file_bytes: Markdown 文档字节数据

        Returns:
            提取的文本内容
        """
        try:
            # Decode bytes to string
            md_content = file_bytes.decode('utf-8')

            # Convert markdown to HTML
            html = markdown.markdown(md_content)

            # Strip HTML tags
            text = re.sub(r'<[^>]+>', '', html)

            # Remove extra blank lines (more than 2 consecutive newlines)
            text = re.sub(r'\n\n+', '\n\n', text)

            logger.info(f"Successfully parsed Markdown document")
            return text.strip()
        except Exception as e:
            logger.error(f"Markdown parsing error: {e}")
            raise
