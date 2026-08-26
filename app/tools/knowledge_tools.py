"""创建供 Agent 管理和检索知识库的工具。"""


from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt

from app.knowledge import KnowledgeBaseService


def create_knowledge_tools(
    service: KnowledgeBaseService,
    owner_id: str,
) -> list[BaseTool]:
    """为指定用户创建知识库工具。"""
    @tool
    def ingest_knowledge_document(filename: str) -> str:
        """导入知识库目录中的文档；仅在用户明确要求导入文件时调用。"""
        result = service.ingest(
            owner_id=owner_id,
            filename=filename,
        )

        if result.already_indexed:
            return (
                f"文档 {result.source_name} 已经存在于知识库中，"
                f"共 {result.chunk_count} 个文本块，无需重复导入。"
            )

        return (
            f"成功导入文档 {result.source_name}，"
            f"共生成 {result.chunk_count} 个文本块。"
        )

    @tool
    def search_knowledge_base(query: str) -> str:
        """检索个人文档内容；涉及用户资料或知识文件的问题应调用此工具。"""
        documents = service.search(
            owner_id=owner_id,
            query=query,
        )

        if not documents:
            return "个人知识库中没有找到与该问题相关的内容。"

        sections: list[str] = []

        for index, document in enumerate(documents, start=1):
            source_name = document.metadata.get(
                "source_name",
                "未知来源",
            )
            page = document.metadata.get("page")

            source_label = source_name

            if page is not None:
                source_label += f"，第 {page} 页"

            sections.append(
                f"资料 {index}（来源：{source_label}）\n"
                f"{document.page_content}"
            )

        return "\n\n".join(sections)

    @tool
    def list_knowledge_documents() -> str:
        """列出当前用户已经导入知识库的文档。"""
        sources = service.list_sources(owner_id)

        if not sources:
            return "个人知识库目前为空。"

        return "\n".join(
            f"- {source.source_name}："
            f"{source.chunk_count} 个文本块"
            for source in sources
        )

    @tool
    def delete_knowledge_document(filename: str) -> str:
        """请求永久删除知识文档；执行前必须获得用户审批。"""
        decision = interrupt(
            {
                "kind": "tool_approval",
                "tool_name": (
                    "delete_knowledge_document"
                ),
                "message": (
                    "是否确认从知识库删除"
                    "这个文档？"
                ),
                "arguments": {
                    "filename": filename,
                },
            }
        )

        if (
                not isinstance(decision, dict)
                or decision.get("approved")
                is not True
        ):
            return (
                "用户拒绝删除知识库文档，"
                "操作已取消。"
            )

        deleted = service.delete_source(
            owner_id=owner_id,
            filename=filename,
        )

        if not deleted:
            return f"知识库中不存在文档：{filename}"

        return f"已从知识库删除文档：{filename}"

    return [
        ingest_knowledge_document,
        search_knowledge_base,
        list_knowledge_documents,
        delete_knowledge_document,
    ]