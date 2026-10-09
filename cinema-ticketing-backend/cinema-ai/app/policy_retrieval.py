"""Retrieve bounded policy candidates with stable source and chunk identifiers."""

import hashlib
import re
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import Field

KNOWLEDGE_PATH = Path(__file__).resolve().parent.parent / "knowledge"


def keyword_terms(text: str) -> set[str]:
    """Use the existing Chinese-character and Latin-word overlap baseline."""
    return set(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower()))


def split_documents(content: str, metadata: dict[str, Any]) -> list[Document]:
    """Keep local and database passages within the same small input budget."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=80,
        separators=["\n\n", "\n", "。", "，", " ", ""],
    )
    documents = splitter.create_documents([content], metadatas=[metadata])
    for index, document in enumerate(documents):
        identity = f"{metadata.get('source')}:{metadata.get('id', '')}:{metadata.get('version', '')}:{index}:{document.page_content}"
        document.metadata["chunk_id"] = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return documents


class KeywordRetriever(BaseRetriever):
    """Recall local policy candidates for subsequent semantic reranking."""

    documents: list[Document] = Field(default_factory=list)
    top_k: int = 20

    def _get_relevant_documents(self, query: str, *, run_manager: Any) -> list[Document]:
        query_terms = keyword_terms(query)
        ranked = [(len(query_terms & keyword_terms(document.page_content)), document) for document in self.documents]
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [document for score, document in ranked[: self.top_k] if score]


def load_retriever() -> KeywordRetriever:
    """Load direct Markdown children once at Agent startup."""
    documents = []
    for source in sorted(KNOWLEDGE_PATH.glob("*.md")):
        documents.extend(
            split_documents(source.read_text(encoding="utf-8"), {"source": source.name, "version": "2026.01"})
        )
    return KeywordRetriever(documents=documents)


def policy_candidates(
    question: str,
    local_documents: list[Document],
    business_documents: list[dict[str, Any]],
    limit: int,
) -> list[Document]:
    """Merge public knowledge sources, deduplicate content, and retain the keyword fallback order."""
    documents = list(local_documents)
    for row in business_documents:
        metadata = {"source": "knowledge_document", **{key: value for key, value in row.items() if key != "content"}}
        documents.extend(split_documents(row["content"], metadata))
    seen = set()
    unique = []
    for document in documents:
        content = document.page_content.strip()
        if content and content not in seen:
            seen.add(content)
            unique.append(document)
    terms = keyword_terms(question)
    unique.sort(
        key=lambda doc: len(terms & keyword_terms(doc.page_content + " " + str(doc.metadata.get("title", "")))),
        reverse=True,
    )
    return unique[:limit]
