"""
Step 2 — Parse product catalog files (.md/.mdx/.txt/.pdf) from a local directory.

Markdown is split by H1-H3 headings; PDFs are split per page; TXT is one block.
The directory is provided by the DOCS_DIR environment variable (no git clone).
"""

import os
import re
from pathlib import Path

from dotenv import load_dotenv
from app.utils.logger import get_logger

load_dotenv()

log = get_logger(__name__)

DOCS_DIR = os.path.abspath(os.getenv("DOCS_DIR", "./data_docs"))
TEXT_EXT = {".md", ".mdx", ".txt"}
PDF_EXT = {".pdf"}


def _extract_frontmatter_title(content: str) -> tuple[str, str]:
    """Strip YAML frontmatter and return (title, remaining_content)."""
    title = ""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            frontmatter = content[3:end]
            for line in frontmatter.splitlines():
                if line.startswith("title:"):
                    title = line.split("title:", 1)[1].strip().strip('"').strip("'")
            content = content[end + 3:].strip()
    return title, content


def _split_by_headings(content: str) -> list[tuple[str, str]]:
    """
    Split markdown content by headings (H1-H3).
    Returns list of (heading, body) tuples.
    """
    heading_pattern = re.compile(r'^(#{1,3})\s+(.+)$', re.MULTILINE)
    matches = list(heading_pattern.finditer(content))

    if not matches:
        return [("", content.strip())]

    sections = []
    for i, match in enumerate(matches):
        heading_text = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        if body:
            sections.append((heading_text, body))

    return sections


def _parse_text_file(file_path: Path, rel_path: str) -> list[dict]:
    """Parse a markdown/text file into heading-based sections."""
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    fm_title, cleaned = _extract_frontmatter_title(content)
    file_title = fm_title or file_path.stem.replace("-", " ").replace("_", " ").strip()

    sections = _split_by_headings(cleaned)
    return [
        {
            "title": file_title,
            "section": heading or file_title,
            "content": body,
            "file_path": rel_path,
        }
        for heading, body in sections
    ]


def _parse_pdf_file(file_path: Path, rel_path: str) -> list[dict]:
    """Extract text from a PDF; each page becomes one section."""
    from pypdf import PdfReader

    reader = PdfReader(str(file_path))
    file_title = file_path.stem.replace("_", " ").replace("-", " ").strip()
    sections = []

    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if text:
            sections.append({
                "title": file_title,
                "section": f"{file_title} - {i + 1}ページ",
                "content": text,
                "file_path": rel_path,
            })

    return sections


def parse_docs(docs_dir: str = DOCS_DIR) -> list[dict]:
    """
    Walk the catalog directory recursively and parse all supported files.
    Returns a list of raw section dicts (pre-chunking).
    """
    docs_dir = os.path.abspath(docs_dir)
    if not os.path.isdir(docs_dir):
        raise FileNotFoundError(f"Docs directory not found: {docs_dir}")

    supported = TEXT_EXT | PDF_EXT
    doc_files = sorted(
        p for p in Path(docs_dir).rglob("*")
        if p.is_file() and p.suffix.lower() in supported
    )

    log.info("parser.docs_discovered", files=len(doc_files), docs_dir=docs_dir)

    raw_sections = []
    for file_path in doc_files:
        rel_path = str(file_path.relative_to(docs_dir)).replace("\\", "/")
        try:
            if file_path.suffix.lower() in PDF_EXT:
                raw_sections.extend(_parse_pdf_file(file_path, rel_path))
            else:
                raw_sections.extend(_parse_text_file(file_path, rel_path))
        except Exception as e:
            log.warning("parser.read_error", file_path=str(file_path), error=str(e))

    log.info("parser.done", sections=len(raw_sections))
    return raw_sections


if __name__ == "__main__":
    sections = parse_docs()
    log.info("parser.sample", sections=len(sections), sample=sections[0] if sections else "none")
