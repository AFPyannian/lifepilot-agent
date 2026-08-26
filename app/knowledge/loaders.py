"""将受支持的知识文件加载为 LangChain 文档。"""


from pathlib import Path

from langchain_core.documents import Document
from pypdf import PdfReader


SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf"}


def load_source_documents(file_path: Path) -> list[Document]:
    """根据扩展名加载 TXT、Markdown 或 PDF 文档。"""
    suffix = file_path.suffix.lower()

    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"不支持的文件类型：{suffix}，目前只支持 TXT、Markdown 和 PDF"
        )

    if suffix in {".txt", ".md"}:
        content = file_path.read_text(encoding="utf-8")

        if not content.strip():
            raise ValueError("文档内容为空")

        return [
            Document(
                page_content=content,
                metadata={},
            )
        ]

    return _load_pdf(file_path)


def _load_pdf(file_path: Path) -> list[Document]:
    """逐页提取 PDF 文本并跳过空白页。"""
    reader = PdfReader(str(file_path))
    documents: list[Document] = []

    for page_number, page in enumerate(reader.pages, start=1):
        content = page.extract_text() or ""


        if not content.strip():
            continue

        documents.append(
            Document(
                page_content=content,
                metadata={"page": page_number},
            )
        )

    if not documents:
        raise ValueError(
            "没有从 PDF 中提取到文字。扫描版 PDF 需要 OCR，本阶段暂不支持。"
        )

    return documents