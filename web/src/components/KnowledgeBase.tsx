import { Activity, ChevronRight, Database, FileBox, FileText, Search, Zap } from "lucide-react";

export default function KnowledgeBase() {
  return (
    <section
      className="h-full flex flex-col"
      style={{
        backgroundColor: "#ffffff",
        borderRight: "1px solid rgba(0,0,0,0.07)",
      }}
    >
      <div className="p-6">
        <h2 className="text-[15px] font-semibold text-[#111113] tracking-tight mb-5">
          ナレッジとランタイム
        </h2>

        <div
          className="rounded-2xl p-5 flex flex-col transition-all duration-200"
          style={{
            background: "linear-gradient(145deg, #fafafa 0%, #f5f5f7 100%)",
            border: "1px solid rgba(0,0,0,0.07)",
            boxShadow: "0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.03)",
          }}
        >
          <div className="flex items-center gap-3 mb-4">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
              style={{
                background: "linear-gradient(135deg, rgba(37,99,235,0.1) 0%, rgba(124,58,237,0.1) 100%)",
                border: "1px solid rgba(37,99,235,0.15)",
              }}
            >
              <Database size={17} style={{ color: "#2563eb" }} />
            </div>
            <div>
              <h3 className="text-[13px] font-semibold text-[#1c1c1e]">運用ナレッジベース</h3>
              <p className="text-[11px]" style={{ color: "#a0a0ab" }}>
                公式Next.jsドキュメントのクローン + BM25コーパス + ChromaDB + セマンティックキャッシュ
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <MetricCard label="埋め込みモデル" value="all-MiniLM-L6-v2" color="#2563eb" />
            <MetricCard label="リランカー" value="ms-marco-L-6-v2" color="#7c3aed" />
            <MetricCard label="ウォームパス" value="セマンティックキャッシュ" color="#059669" />
            <MetricCard label="API" value="FastAPI" color="#d97706" />
          </div>
        </div>
      </div>

      <div className="mx-6" style={{ height: "1px", backgroundColor: "rgba(0,0,0,0.05)" }} />

      <div className="px-6 pt-5 pb-3">
        <div className="flex items-center gap-1.5 text-[12px]" style={{ color: "#a0a0ab" }}>
          <span className="hover:text-[#1c1c1e] cursor-pointer transition-colors">ランタイム</span>
          <ChevronRight size={12} />
          <span className="font-medium" style={{ color: "#1c1c1e" }}>有効なアセット</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-6 space-y-1">
        <AssetRecord
          icon={<FileText size={14} style={{ color: "#2563eb" }} />}
          iconBg="rgba(37,99,235,0.08)"
          name="data/nextjs-repo"
          status="ソースコーパス"
          statusColor="#2563eb"
          statusBg="rgba(37,99,235,0.08)"
          detail="クローンされた公式ドキュメントリポジトリ"
          side="ローカル"
          active
        />
        <AssetRecord
          icon={<Database size={14} style={{ color: "#7c3aed" }} />}
          iconBg="rgba(124,58,237,0.08)"
          name="data/chroma_db"
          status="ベクトルストア"
          statusColor="#7c3aed"
          statusBg="rgba(124,58,237,0.08)"
          detail="永続的な意味検索インデックス"
          side="ディスク"
        />
        <AssetRecord
          icon={<Search size={14} style={{ color: "#059669" }} />}
          iconBg="rgba(5,150,105,0.08)"
          name="data/bm25_corpus.json"
          status="キーワードインデックス"
          statusColor="#059669"
          statusBg="rgba(5,150,105,0.08)"
          detail="BM25用にトークン化された検索コーパス"
          side="JSON"
        />
        <AssetRecord
          icon={<Zap size={14} style={{ color: "#d97706" }} />}
          iconBg="rgba(217,119,6,0.08)"
          name="semantic_cache"
          status="ウォームパス"
          statusColor="#d97706"
          statusBg="rgba(217,119,6,0.08)"
          detail="類似する質問ではグラフ実行をスキップ"
          side="高速"
        />
        <AssetRecord
          icon={<FileBox size={14} style={{ color: "#dc2626" }} />}
          iconBg="rgba(220,38,38,0.08)"
          name="/source/download"
          status="追跡機能"
          statusColor="#dc2626"
          statusBg="rgba(220,38,38,0.08)"
          detail="ローカルクローンから引用元の.mdxファイルをダウンロード"
          side="HTTP"
        />
        <AssetRecord
          icon={<Activity size={14} style={{ color: "#0f766e" }} />}
          iconBg="rgba(15,118,110,0.08)"
          name="data/eval/*.json"
          status="ベンチマーク"
          statusColor="#0f766e"
          statusBg="rgba(15,118,110,0.08)"
          detail="コールド/ウォームのレイテンシレポート"
          side="評価"
        />
      </div>
    </section>
  );
}

function MetricCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div
      className="rounded-xl p-3"
      style={{
        backgroundColor: "rgba(0,0,0,0.03)",
        border: "1px solid rgba(0,0,0,0.06)",
      }}
    >
      <div
        className="text-[10px] font-semibold uppercase tracking-wide mb-1"
        style={{ color: "#a0a0ab" }}
      >
        {label}
      </div>
      <div className="text-[12px] font-medium" style={{ color }}>
        {value}
      </div>
    </div>
  );
}

function AssetRecord({
  icon,
  iconBg,
  name,
  status,
  statusColor,
  statusBg,
  detail,
  side,
  active = false,
}: {
  icon: React.ReactNode;
  iconBg: string;
  name: string;
  status: string;
  statusColor: string;
  statusBg: string;
  detail: string;
  side: string;
  active?: boolean;
}) {
  return (
    <div
      className="grid grid-cols-[1fr_88px_58px] gap-4 items-center px-3 py-2.5 rounded-xl transition-all duration-150 cursor-default"
      style={
        active
          ? {
              backgroundColor: "#f5f5f7",
              border: "1px solid rgba(0,0,0,0.07)",
            }
          : {
              border: "1px solid transparent",
            }
      }
      onMouseEnter={(e) => {
        if (!active) (e.currentTarget as HTMLElement).style.backgroundColor = "#f9f9fb";
      }}
      onMouseLeave={(e) => {
        if (!active) (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
      }}
    >
      <div className="flex items-center gap-2.5 overflow-hidden">
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
          style={{ backgroundColor: iconBg }}
        >
          {icon}
        </div>
        <div className="min-w-0">
          <div className="text-[13px] font-medium truncate" style={{ color: "#1c1c1e" }}>
            {name}
          </div>
          <div className="text-[11px] truncate" style={{ color: "#a0a0ab" }}>
            {detail}
          </div>
        </div>
      </div>

      <div className="flex justify-center">
        <span
          className="text-[10px] font-semibold px-2 py-0.5 rounded-full text-center"
          style={{ color: statusColor, backgroundColor: statusBg }}
        >
          {status}
        </span>
      </div>

      <div className="text-[11px] text-right" style={{ color: "#a0a0ab" }}>
        {side}
      </div>
    </div>
  );
}
