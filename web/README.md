# trade_knowledge Web

`trade_knowledge` のユーザー向け Web アプリケーション（Next.js 16）。API のチャット機能を対話的に操作するフロントエンドです。

## 役割

- 商品カタログ・在庫・受注・入荷のチャット照会 UI
- SSE（`/ask/stream`）による回答の**逐字ストリーミング**
- 「実行トレース」パネルによる LLM 呼出・SQL・ツール呼出の可視化
- 業務カード（在庫照会 / 入出荷・物流 / 発注推奨）と出典バッジの表示
- Markdown レンダリング（GFM テーブル対応）
- ブラウザ localStorage による会話履歴（保存・切替・継続・削除）

## ルート

- `/` — チャット画面

## 主な構成

```text
src/
├── app/
│   ├── page.tsx                 # ChatProvider + チャット画面
│   └── layout.tsx               # メタデータ（title / description）
├── components/
│   ├── ChatPanel.tsx            # チャット本体（ストリーム受信・レンダリング）
│   ├── Sidebar.tsx              # 新規チャット / 履歴を開く縦型バー
│   ├── HistoryPanel.tsx         # 会話履歴ドロワー
│   └── ...                      # 業務カード・実行トレース等
└── context/
    └── ChatContext.tsx          # 会話状態・SSE 処理・localStorage 永続化
```

## 状態管理

- 会話セッションとメッセージは React Context（`ChatContext`）で管理
- デモ用に `localStorage`（キー `trade_knowledge_sessions_v1`）へ永続化し、更新後は「生成中」状態を復元しない
- 最新の最大 24 セッションを保持（空間不足時は 8 件に縮小）

## 開発

```bash
npm install
npm run dev      # 開発サーバ
npm run build    # 本番ビルド
npm run lint
```

API 接続先はビルド引数 `NEXT_PUBLIC_API_BASE_URL`（既定 `http://localhost:8000`）で設定します。

## 作者

**Zhiyuan Sun** — GitHub: [ZhiyuanLabs](https://github.com/ZhiyuanLabs)
