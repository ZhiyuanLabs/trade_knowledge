"""
Japanese-aware BM25 tokenizer — used at both index time (ingestion) and query time.

Consistency is critical: the same tokenization logic MUST be applied to corpus chunks
and search queries, otherwise BM25 scores become meaningless.

Strategy:
  - Japanese runs (hiragana / katakana / kanji / half-width katakana) are tokenized
    into overlapping character bigrams. Japanese has no word boundaries, so bigrams
    give robust matching for fruit names, katakana terms and document numbers.
  - ASCII alphanumeric runs (product codes like "FRT-BAN-001", "SO-2026-1101",
    "RC-7001") are kept as whole lowercased tokens.
"""

import re

# Either an ASCII alphanumeric token (internal dots/hyphens kept, e.g. "FRT-BAN-001",
# "SO-2026-1101", "RC-7001"), a single ASCII char, or a Japanese character run.
# Japanese Unicode blocks: hiragana (3040-309F), katakana (30A0-30FF),
# CJK extension A (3400-4DBF), CJK unified ideographs (4E00-9FFF),
# half-width katakana (FF66-FF9F).
_JP_RUN = r"[぀-ゟ゠-ヿ㐀-䶿一-鿿ｦ-ﾟ]+"
_TOKEN_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9]|[A-Za-z0-9]|" + _JP_RUN
)

# Minimal English stopword set (catalogs may contain English specs).
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "it", "its", "this", "that", "these", "those", "not", "no", "if",
})


def tokenize(text: str) -> list[str]:
    """
    Tokenize Japanese/English text for BM25 indexing and querying.

    - ASCII runs -> lowercased whole tokens (stopwords and single chars removed)
    - Japanese runs -> overlapping character bigrams (single char kept as-is)
    """
    tokens: list[str] = []

    for seg in _TOKEN_RE.findall(text):
        if re.fullmatch(r"[A-Za-z0-9.\-]+", seg):
            token = seg.lower()
            if token in _STOPWORDS or len(token) < 2:
                continue
            tokens.append(token)
        else:
            # Japanese character run -> bigrams
            if len(seg) == 1:
                tokens.append(seg)
            else:
                for i in range(len(seg) - 1):
                    tokens.append(seg[i:i + 2])

    return tokens
