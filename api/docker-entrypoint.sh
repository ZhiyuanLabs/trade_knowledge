#!/bin/sh
set -eu

if [ "${AUTO_INGEST_ON_BOOT:-false}" = "true" ] && [ "${1:-}" = "uvicorn" ]; then
  chroma_root="${CHROMA_PATH:-/app/data/chroma_db}"
  chroma_sqlite="${chroma_root}/chroma.sqlite3"
  bm25_corpus="${BM25_CORPUS_PATH:-/app/data/bm25_corpus.json}"
  chunks_path="${CHUNKS_PATH:-/app/data/chunks.json}"

  if [ ! -f "$bm25_corpus" ] || [ ! -f "$chunks_path" ] || [ ! -f "$chroma_sqlite" ]; then
    echo "[docker-entrypoint] Retrieval artifacts not found. Running ingestion before API startup."
    python -m ingestion.indexer
  fi
fi

exec "$@"
