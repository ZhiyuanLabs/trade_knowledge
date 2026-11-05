# trade_knowledge API

`trade_knowledge` のコアランタイム。FastAPI と LangGraph で構築した、商品カタログ RAG と業務データ照会を統合するエージェントのバックエンドです。

## 役割

- 商品カタログ文書のインジェスト・インデックス構築（BM25 + ChromaDB）
- LangGraph による明示的なエージェントループ（意図ルーティング／検索／ツール呼出／証拠／合成）
- SQLite 業務データベースへのツールアクセス
- 通常応答と SSE ストリーミング応答の提供

## HTTP エンドポイント

| メソッド / パス | 内容 |
|---|---|
| `GET /health` | ヘルスチェック |
| `POST /ask` | 通常応答（`{ answer, citations, evidence_score, from_cache, route, business_result }`） |
| `POST /ask/stream` | SSE ストリーミング（`cache / node / llm / sql / tool / answer_delta / final / error`） |
| `GET /source/download?path=...` | 文書原文（PDF / Word / Excel / Markdown / テキスト）のダウンロード |

## LangGraph ノード構成

```text
START
  └─ intent_router            # LLM が catalog / business / hybrid に分類
       ├─ business ─▶ business_agent ─▶ business_tools ─▶ planner
       └─ catalog / hybrid ─▶ planner
            planner ─▶ decomposition_router
                       └─ retrieval_specialist ─▶ retriever
                            (BM25 + ベクトル) ─▶ reranker ─▶ chunk_reader
                                                                 └─ (証拠不足なら再分解)
            └─ 証拠十分 ─▶ final_synthesizer ─▶ END
```

## 業務ツール（`app/tools/business_tools.py`）

| ツール | 内容 |
|---|---|
| `query_stock` | 在庫照会 |
| `query_orders` | 受注照会 |
| `query_shipments` | 入出荷・物流照会 |
| `check_low_stock` | 安全在庫割れの検知と発注推奨 |
| `run_tools` | 複数ツールをまとめて実行 |

`app/tools/database.py` が SQLite（`/app/data/business.db`）への接続とシードを管理します。テーブルは `products` / `orders` / `shipments` です。

## 検索スタック

- 埋め込み: sentence-transformers（ローカル）
- ベクトル DB: ChromaDB（ローカル）
- キーワード: rank-bm25
- リランカー: ローカルモデル
- 生成 LLM: OpenAI 互換 API（`.env` でプロバイダ／モデルを差し替え）

## 設定

`.env.example` を `.env` にコピーして設定します。

```text
LLM_PROVIDER=openai
OPENAI_BASE_URL=...
OPENAI_API_KEY=...
LLM_MODEL=...
RESPONSE_LANGUAGE=japanese
```

## テスト・評価

```bash
python -m pytest                                      # ノード・グラフ構造のテスト
python eval/run_eval.py --validate-only               # 40件の金標準データを検証
python eval/run_eval.py --skip-faithfulness           # 決定論的な全指標
python eval/run_eval.py                                # 上記 + Ragas Faithfulness
python eval/benchmark_api.py                           # コールド/ウォームのレイテンシ計測
python debug_pipeline.py                               # LLM 接続・パイプライン診断
```

評価データは `eval/trade_knowledge_eval.json` にあり、日本語の catalog / business /
hybrid / refusal を計40件収録しています。結果は `data/eval/` に JSON と CSV で保存され、
ルート正解率、検索 Recall@5、業務データ正確率、拒答正解率、キャッシュ整合性、
Faithfulness、平均・P50・P95応答時間を記録します。業務数値は生成文ではなく
`business_result` をDBの期待値と完全一致で評価します。

評価器はアプリ本体と同じ `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `LLM_MODEL` を使います。
管理環境では `DEEPSEEK_API_KEY` も `OPENAI_API_KEY` の代替として利用できます。

## 作者

**Zhiyuan Sun** — GitHub: [ZhiyuanLabs](https://github.com/ZhiyuanLabs)
