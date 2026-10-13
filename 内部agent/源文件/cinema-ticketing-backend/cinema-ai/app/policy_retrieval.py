"""Retrieve bounded policy candidates with stable source and chunk identifiers."""

# 导入当前步骤使用的模块或类型。
# isort: off
import hashlib
# 导入当前步骤使用的模块或类型。
import re
# 导入当前步骤使用的模块或类型。
from pathlib import Path
# 导入当前步骤使用的模块或类型。
from typing import Any

# 导入当前步骤使用的模块或类型。
from langchain_core.documents import Document
# 导入当前步骤使用的模块或类型。
from langchain_core.retrievers import BaseRetriever
# 导入当前步骤使用的模块或类型。
from langchain_text_splitters import RecursiveCharacterTextSplitter
# 导入当前步骤使用的模块或类型。
from pydantic import Field
# isort: on

# 为 `KNOWLEDGE_PATH` 保存当前步骤所需的值。
KNOWLEDGE_PATH = Path(__file__).resolve().parent.parent / "knowledge"


# 声明当前处理单元及其入口。
def keyword_terms(text: str) -> set[str]:
    """Use the existing Chinese-character and Latin-word overlap baseline."""
    # 将当前计算结果返回给调用方。
    return set(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower()))


# 声明当前处理单元及其入口。
def split_documents(content: str, metadata: dict[str, Any]) -> list[Document]:
    """Keep local and database passages within the same small input budget."""
    # 为 `splitter` 保存当前步骤所需的值。
    splitter = RecursiveCharacterTextSplitter(
        # 为 `chunk_size` 保存当前步骤所需的值。
        chunk_size=500,
        # 为 `chunk_overlap` 保存当前步骤所需的值。
        chunk_overlap=80,
        # 为 `separators` 保存当前步骤所需的值。
        separators=["\n\n", "\n", "。", "，", " ", ""],
    )
    # 为 `documents` 保存当前步骤所需的值。
    documents = splitter.create_documents([content], metadatas=[metadata])
    # 进入对应的循环、异常处理或资源管理分支。
    for index, document in enumerate(documents):
        # 为 `identity` 保存当前步骤所需的值。
        identity = f"{metadata.get('source')}:{metadata.get('id', '')}:{metadata.get('version', '')}:{index}:{document.page_content}"
        document.metadata["chunk_id"] = hashlib.sha256(identity.encode()).hexdigest()[:24]
    # 将当前计算结果返回给调用方。
    return documents


# 声明当前处理单元及其入口。
class KeywordRetriever(BaseRetriever):
    """Recall local policy candidates for subsequent semantic reranking."""

    # 设置当前结构中的 `documents` 字段。
    documents: list[Document] = Field(default_factory=list)
    # 设置当前结构中的 `top_k` 字段。
    top_k: int = 20

    # 声明当前处理单元及其入口。
    def _get_relevant_documents(self, query: str, *, run_manager: Any) -> list[Document]:
        # 为 `query_terms` 保存当前步骤所需的值。
        query_terms = keyword_terms(query)
        # 为 `ranked` 保存当前步骤所需的值。
        ranked = [(len(query_terms & keyword_terms(document.page_content)), document) for document in self.documents]
        # 继续构造当前业务表达式或数据结构。
        ranked.sort(key=lambda item: item[0], reverse=True)
        # 将当前计算结果返回给调用方。
        return [document for score, document in ranked[: self.top_k] if score]


# 声明当前处理单元及其入口。
def load_retriever() -> KeywordRetriever:
    """Load direct Markdown children once at Agent startup."""
    # 为 `documents` 保存当前步骤所需的值。
    documents = []
    # 进入对应的循环、异常处理或资源管理分支。
    for source in sorted(KNOWLEDGE_PATH.glob("*.md")):
        # 继续构造当前业务表达式或数据结构。
        documents.extend(
            # 调用 `split_documents` 执行当前业务操作。
            split_documents(source.read_text(encoding="utf-8"), {"source": source.name, "version": "2026.01"})
        )
    # 将当前计算结果返回给调用方。
    return KeywordRetriever(documents=documents)


# 声明当前处理单元及其入口。
def policy_candidates(
    # 设置当前结构中的 `question` 字段。
    question: str,
    # 设置当前结构中的 `local_documents` 字段。
    local_documents: list[Document],
    # 设置当前结构中的 `business_documents` 字段。
    business_documents: list[dict[str, Any]],
    # 设置当前结构中的 `limit` 字段。
    limit: int,
# 继续构造当前业务表达式或数据结构。
) -> list[Document]:
    """Merge public knowledge sources, deduplicate content, and retain the keyword fallback order."""
    # 为 `documents` 保存当前步骤所需的值。
    documents = list(local_documents)
    # 进入对应的循环、异常处理或资源管理分支。
    for row in business_documents:
        # 为 `metadata` 保存当前步骤所需的值。
        metadata = {"source": "knowledge_document", **{key: value for key, value in row.items() if key != "content"}}
        documents.extend(split_documents(row["content"], metadata))
    # 为 `seen` 保存当前步骤所需的值。
    seen = set()
    # 为 `unique` 保存当前步骤所需的值。
    unique = []
    # 进入对应的循环、异常处理或资源管理分支。
    for document in documents:
        # 为 `content` 保存当前步骤所需的值。
        content = document.page_content.strip()
        # 检查 `if content and content not in seen`，据此选择当前处理分支。
        if content and content not in seen:
            # 继续构造当前业务表达式或数据结构。
            seen.add(content)
            # 继续构造当前业务表达式或数据结构。
            unique.append(document)
    # 为 `terms` 保存当前步骤所需的值。
    terms = keyword_terms(question)
    # 继续构造当前业务表达式或数据结构。
    unique.sort(
        # 为 `key` 保存当前步骤所需的值。
        key=lambda doc: len(terms & keyword_terms(doc.page_content + " " + str(doc.metadata.get("title", "")))),
        # 为 `reverse` 保存当前步骤所需的值。
        reverse=True,
    )
    # 将当前计算结果返回给调用方。
    return unique[:limit]
