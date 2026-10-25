"""
Step 3 — Chunk sections into token-bounded pieces.
Uses tiktoken for accurate token counting.
"""

import hashlib
import os
import tiktoken
from app.utils.logger import get_logger

MAX_TOKENS = int(os.getenv("MAX_CHUNK_TOKENS", "500"))
OVERLAP_TOKENS = int(os.getenv("CHUNK_OVERLAP_TOKENS", "50"))
log = get_logger(__name__)


def _get_encoder():
    return tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    enc = _get_encoder()
    return len(enc.encode(text))


def _split_text(text: str, max_tokens: int, overlap: int) -> list[str]:
    """Split text into chunks with token overlap."""
    enc = _get_encoder()
    tokens = enc.encode(text)

    if len(tokens) <= max_tokens:
        return [text]

    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(enc.decode(chunk_tokens))
        start += max_tokens - overlap

    return chunks


def _make_chunk_id(file_path: str, section: str, index: int, content: str = "") -> str:
    # Include content prefix to avoid collisions when file+section+index repeats
    raw = f"{file_path}::{section}::{index}::{content[:120]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def chunk_sections(raw_sections: list[dict]) -> list[dict]:
    """
    Takes raw sections from the parser and produces token-bounded chunks.
    Each chunk follows the required DocChunk schema.
    chunk_id uses a global sequential counter — guaranteed unique.
    """
    chunks = []
    doc_counter: dict[str, int] = {}
    global_chunk_idx = 0  # monotonically increasing, no collision possible

    for section in raw_sections:
        file_path = section["file_path"]
        title = section["title"]
        heading = section["section"]
        content = section["content"]

        if not content.strip():
            continue

        text_chunks = _split_text(content, MAX_TOKENS, OVERLAP_TOKENS)

        for i, text in enumerate(text_chunks):
            token_count = _count_tokens(text)

            # Global index + short content hash for readability + debuggability
            content_hash = hashlib.sha256(text.encode()).hexdigest()[:8]
            chunk_id = f"chunk_{global_chunk_idx:05d}_{content_hash}"
            global_chunk_idx += 1

            # Unique doc_id per file
            if file_path not in doc_counter:
                doc_counter[file_path] = len(doc_counter)
            doc_id = f"doc_{doc_counter[file_path]:04d}"

            chunks.append({
                "doc_id": doc_id,
                "title": title,
                "section": heading,
                "content": text,
                "source": os.getenv("SOURCE_LABEL", "product catalog"),
                "file_path": file_path,
                "chunk_id": chunk_id,
                "tokens": token_count,
            })

    log.info("chunker.done", chunks=len(chunks), max_tokens=MAX_TOKENS, overlap_tokens=OVERLAP_TOKENS)
    return chunks


if __name__ == "__main__":
    from ingestion.parser import parse_docs
    from dotenv import load_dotenv
    load_dotenv()
    repo = os.path.abspath(os.getenv("NEXTJS_REPO_PATH", "./data/nextjs-repo"))
    sections = parse_docs(repo)
    chunks = chunk_sections(sections)
    log.info("chunker.sample", sample=chunks[0] if chunks else "none")
