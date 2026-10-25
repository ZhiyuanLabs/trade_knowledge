"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertCircle,
  AlertTriangle,
  ArrowUp,
  Bot,
  ChevronRight,
  ClipboardList,
  Database,
  Download,
  ExternalLink,
  Package,
  Truck,
  Wrench,
  Zap,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import {
  useChatContext,
  Message,
  type BusinessResult,
  type StockRow,
  type OrderRow,
  type ShipmentRow,
  type TraceEvent,
} from "@/context/ChatContext";
import OrbCanvas from "@/components/OrbCanvas";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

interface AskResponse {
  answer: string;
  citations: string[];
  evidence_score: number;
  best_evidence_score: number;
  current_evidence_score: number;
  from_cache: boolean;
  route?: string;
  business_result?: BusinessResult | null;
}

interface CitationMeta {
  raw: string;
  fullPath: string;
  compactPath: string;
  filename: string;
  isWebSearch: boolean;
  isBusiness: boolean;
  sourceHref: string | null;
  downloadHref: string | null;
}

function parseCitation(citation: string): CitationMeta {
  const clean = citation.replace("[Source: ", "").replace("]", "").trim();
  const isWebSearch = clean.endsWith("— web search");
  const isBusiness = clean.startsWith("DB:");
  const path = isWebSearch ? clean.replace(" — web search", "").trim() : clean;
  const segments = path.split("/").filter(Boolean);
  const filename = isBusiness
    ? path.replace(/^DB:\s*/, "")
    : (segments.at(-1) ?? path);
  const compactPath = isBusiness
    ? filename
    : segments.length <= 3
      ? path
      : `${segments[0]}/…/${segments[segments.length - 2]}/${segments[segments.length - 1]}`;
  // Web results link externally; business DB rows are not files;
  // catalog files (md/txt/pdf) are served by the local download endpoint.
  const sourceHref = isWebSearch ? path : null;
  const downloadHref =
    isWebSearch || isBusiness
      ? null
      : `${API_BASE_URL}/source/download?path=${encodeURIComponent(path)}`;

  return {
    raw: citation,
    fullPath: path,
    compactPath,
    filename,
    isWebSearch,
    isBusiness,
    sourceHref,
    downloadHref,
  };
}

function statusColor(status: string): { bg: string; fg: string } {
  if (status.includes("切れ") || status.includes("出荷済")) {
    return { bg: "#fee2e2", fg: "#b91c1c" };
  }
  if (status.includes("わずか") || status.includes("予定") || status.includes("手配") || status.includes("待ち") || status.includes("受注")) {
    return { bg: "#fef3c7", fg: "#b45309" };
  }
  return { bg: "#dcfce7", fg: "#15803d" };
}

function BusinessCards({ data }: { data: BusinessResult }) {
  const hasAlerts = data.alerts?.length > 0;
  const hasStock = data.stock?.length > 0;
  const hasOrders = data.orders?.length > 0;
  const hasShipments = data.shipments?.length > 0;

  if (!hasAlerts && !hasStock && !hasOrders && !hasShipments) return null;

  return (
    <div className="mt-4 space-y-3">
      {/* Purchase recommendations (safety-stock alerts) */}
      {hasAlerts && (
        <div
          className="rounded-2xl p-4"
          style={{ backgroundColor: "#fff7ed", border: "1px solid #fdba74" }}
        >
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle size={15} style={{ color: "#c2410c" }} />
            <span className="text-[13px] font-semibold" style={{ color: "#c2410c" }}>
              発注推奨（安全在庫割れ）
            </span>
          </div>
          <div className="space-y-1.5">
            {data.alerts.map((a) => (
              <div key={a.product_code} className="text-[12.5px] leading-relaxed" style={{ color: "#7c2d12" }}>
                <span className="font-semibold">{a.name}</span>（{a.product_code}）：
                在庫 {a.stock_qty}{a.unit ?? ""} / 安全在庫 {a.safety_stock}{a.unit ?? ""}
                → 推奨発注数 <span className="font-semibold">{a.suggested_purchase_qty}{a.unit ?? ""}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Stock table */}
      {hasStock && (
        <div className="rounded-2xl overflow-hidden" style={{ backgroundColor: "#fafafa", border: "1px solid #ececef" }}>
          <div className="flex items-center gap-2 px-4 py-2.5" style={{ borderBottom: "1px solid #ececef" }}>
            <Package size={14} style={{ color: "#2563eb" }} />
            <span className="text-[12.5px] font-semibold text-[#1c1c1e]">在庫照会</span>
          </div>
          <div className="px-4 py-2">
            {data.stock.map((s: StockRow) => {
              const c = statusColor(s.status);
              return (
                <div key={s.product_code} className="py-2" style={{ borderBottom: "1px solid #f0f0f0" }}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[13px] font-medium text-[#1c1c1e]">{s.name}</span>
                    <span className="text-[10.5px] font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: c.bg, color: c.fg }}>
                      {s.status}
                    </span>
                  </div>
                  <div className="text-[11.5px] text-[#8e8e93] mt-0.5">
                    品番 {s.product_code} ・ 在庫 {s.stock_qty}{s.unit ?? ""}（安全 {s.safety_stock}{s.unit ?? ""}）
                    {s.warehouse ? ` ・ ${s.warehouse}` : ""}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Orders table */}
      {hasOrders && (
        <div className="rounded-2xl overflow-hidden" style={{ backgroundColor: "#fafafa", border: "1px solid #ececef" }}>
          <div className="flex items-center gap-2 px-4 py-2.5" style={{ borderBottom: "1px solid #ececef" }}>
            <ClipboardList size={14} style={{ color: "#7c3aed" }} />
            <span className="text-[12.5px] font-semibold text-[#1c1c1e]">受注照会</span>
          </div>
          <div className="px-4 py-2">
            {data.orders.map((o: OrderRow) => {
              const c = statusColor(o.status ?? "");
              return (
                <div key={o.order_no} className="py-2" style={{ borderBottom: "1px solid #f0f0f0" }}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[13px] font-medium text-[#1c1c1e]">{o.order_no}</span>
                    <span className="text-[10.5px] font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: c.bg, color: c.fg }}>
                      {o.status}
                    </span>
                  </div>
                  <div className="text-[11.5px] text-[#8e8e93] mt-0.5">
                    {o.customer} ・ {o.product_name} × {o.qty}{o.unit ?? ""}
                    {o.due_date ? ` ・ 納期 ${o.due_date}` : ""}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Shipments table */}
      {hasShipments && (
        <div className="rounded-2xl overflow-hidden" style={{ backgroundColor: "#fafafa", border: "1px solid #ececef" }}>
          <div className="flex items-center gap-2 px-4 py-2.5" style={{ borderBottom: "1px solid #ececef" }}>
            <Truck size={14} style={{ color: "#059669" }} />
            <span className="text-[12.5px] font-semibold text-[#1c1c1e]">入出荷・物流</span>
          </div>
          <div className="px-4 py-2">
            {data.shipments.map((s: ShipmentRow) => {
              const c = statusColor(s.status ?? "");
              return (
                <div key={s.shipment_no} className="py-2" style={{ borderBottom: "1px solid #f0f0f0" }}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[13px] font-medium text-[#1c1c1e]">{s.shipment_no} ・ {s.direction}</span>
                    <span className="text-[10.5px] font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: c.bg, color: c.fg }}>
                      {s.status}
                    </span>
                  </div>
                  <div className="text-[11.5px] text-[#8e8e93] mt-0.5">
                    {s.product_name} × {s.qty}{s.unit ?? ""}
                    {s.date_or_eta ? ` ・ ${s.date_or_eta}` : ""}
                    {s.warehouse ? ` ・ ${s.warehouse}` : ""}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function formatScore(score?: number): string {
  return typeof score === "number" ? score.toFixed(4) : "—";
}

function buildErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message && error.message !== "Failed to fetch") {
    return error.message;
  }
  return `バックエンドに接続できません。${API_BASE_URL} でAPIが起動しているか確認してください。`;
}

const markdownComponents: Components = {
  p: ({ children }) => (
    <p className="mb-4 last:mb-0">{children}</p>
  ),
  h1: ({ children }) => (
    <h1 className="text-[19px] font-semibold text-[#0d0d0d] mb-3 mt-5 tracking-tight">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-[17px] font-semibold text-[#0d0d0d] mb-2.5 mt-5 tracking-tight">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-[15px] font-semibold text-[#0d0d0d] mb-2 mt-4 tracking-tight">{children}</h3>
  ),
  ul: ({ children }) => (
    <ul className="mb-4 space-y-1.5 pl-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-4 space-y-1.5 pl-0 list-decimal list-inside">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="flex items-start gap-2.5 text-[15px]">
      <span className="mt-[7px] w-1.5 h-1.5 rounded-full bg-[#aeaeb2] shrink-0" />
      <span className="flex-1">{children}</span>
    </li>
  ),
  code: ({ children, className, ...props }) => {
    const isBlockCode = Boolean(className);

    return (
      <code
        className={`font-mono text-[13px] ${className ?? ""}`.trim()}
        style={
          isBlockCode
            ? { color: "#1a1a1a" }
            : { backgroundColor: "#f0f0f0", color: "#c7254e", padding: "0.125rem 0.375rem", borderRadius: "0.375rem" }
        }
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <div
      className="rounded-2xl overflow-hidden my-4"
      style={{ border: "1px solid #e5e5e7", backgroundColor: "#f8f8f8" }}
    >
      <div
        className="flex items-center justify-between px-4 py-2"
        style={{ borderBottom: "1px solid #e5e5e7", backgroundColor: "#f2f2f2" }}
      >
        <span className="text-[11px] font-mono" style={{ color: "#aeaeb2" }}>コード</span>
        <div className="flex gap-1.5">
          {["#f87171", "#fbbf24", "#4ade80"].map((c, i) => (
            <div key={i} className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: c, opacity: 0.65 }} />
          ))}
        </div>
      </div>
      <pre className="overflow-x-auto px-4 py-4 text-[13px] leading-6" style={{ color: "#1a1a1a" }}>
        {children}
      </pre>
    </div>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-[#111113]">{children}</strong>
  ),
  blockquote: ({ children }) => (
    <blockquote
      className="my-4 px-4 py-3 rounded-xl text-[14px] italic"
      style={{ backgroundColor: "#f4f4f5", borderLeft: "3px solid #d1d1d6", color: "#6e6e80" }}
    >
      {children}
    </blockquote>
  ),
  table: ({ children }) => (
    <div className="my-4 overflow-x-auto rounded-xl" style={{ border: "1px solid #e5e5e7" }}>
      <table className="border-collapse text-[13px] min-w-full">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead style={{ backgroundColor: "#f4f4f5" }}>{children}</thead>,
  th: ({ children }) => (
    <th className="text-left font-semibold px-3 py-2 whitespace-nowrap" style={{ borderBottom: "1px solid #e5e5e7", color: "#1d1d1f" }}>
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="px-3 py-2 align-top" style={{ borderBottom: "1px solid #efeff1", color: "#3a3a3c" }}>
      {children}
    </td>
  ),
};

// ── Execution trace (demo panel) ─────────────────────────────────────────────
const KIND_STYLE: Record<
  TraceEvent["kind"],
  { color: string; bg: string; border: string; Icon: typeof Bot; label: string }
> = {
  llm: { color: "#c06900", bg: "#fff5e8", border: "#ffd9a8", Icon: Bot, label: "LLM" },
  sql: { color: "#167a35", bg: "#e9f8ee", border: "#b6e4c4", Icon: Database, label: "SQL" },
  tool: { color: "#0a65c2", bg: "#eaf3ff", border: "#bcdcff", Icon: Wrench, label: "TOOL" },
  node: { color: "#3b4252", bg: "#eef1f6", border: "#d8dde7", Icon: ChevronRight, label: "NODE" },
  cache: { color: "#7c3aed", bg: "#f3ecfe", border: "#ddc9f7", Icon: Zap, label: "CACHE" },
  info: { color: "#5a5a60", bg: "#f4f4f5", border: "#e5e5ea", Icon: ChevronRight, label: "INFO" },
};

const preBlock: React.CSSProperties = {
  margin: 0,
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  fontSize: 10.5,
  lineHeight: 1.55,
  fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace",
  background: "#1f2430",
  color: "#d6dce8",
  padding: "8px 10px",
  borderRadius: 8,
  maxHeight: 190,
  overflowY: "auto",
};

function TraceRow({ ev }: { ev: TraceEvent }) {
  const s = KIND_STYLE[ev.kind];
  const Icon = s.Icon;
  let title = ev.title || ev.label || ev.tool || ev.table || "";
  let detail = ev.detail || "";

  if (ev.kind === "llm") {
    title = ev.label || "LLM";
    detail = ev.error
      ? `エラー: ${ev.error}`
      : ev.phase === "start"
        ? ev.stream ? "トークンをストリーミング中…" : "プロンプトを送信・待機中…"
        : "LLM 応答を受信";
  } else if (ev.kind === "sql") {
    title = `SQL: ${ev.table}`;
    detail = `keyword=${ev.keyword || "(全件)"} → ${ev.rows} 行`;
  } else if (ev.kind === "tool") {
    title = `Tool call: ${ev.tool}`;
    detail = `keyword=${ev.keyword || "(全件)"} → ${ev.rows} 行` +
      (ev.alerts ? ` / アラート ${ev.alerts} 件` : "");
  } else if (ev.kind === "cache") {
    title = ev.hit ? "セマンティックキャッシュ HIT" : "キャッシュ判定";
    detail = ev.reason || "";
  }

  const hasDetail = Boolean(ev.system || ev.user || ev.output || ev.sql || ev.params);

  return (
    <div className="rounded-xl px-3 py-2" style={{ background: s.bg, border: `1px solid ${s.border}` }}>
      <div className="flex items-start gap-2">
        <span
          className="mt-0.5 shrink-0 inline-flex items-center justify-center w-5 h-5 rounded-md"
          style={{ background: s.color, color: "#fff" }}
        >
          <Icon size={12} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] font-bold tracking-wide" style={{ color: s.color }}>{s.label}</span>
            <span className="text-[12.5px] font-semibold text-[#1c1c1e] break-all">{title}</span>
            {ev.pending && <span className="text-[11px] text-[#8e8e93] animate-pulse">…</span>}
            {typeof ev.elapsed === "number" && (
              <span className="ml-auto text-[10.5px] tabular-nums text-[#9a9aa0]">+{ev.elapsed.toFixed(2)}s</span>
            )}
          </div>
          {detail && <div className="text-[11.5px] text-[#5a5a60] mt-0.5 break-all">{detail}</div>}
          {hasDetail && (
            <details className="mt-1.5">
              <summary className="text-[11px] cursor-pointer text-[#6e6e80] select-none underline decoration-dotted underline-offset-2">
                プロンプト / SQL / 応答を表示
              </summary>
              <div className="mt-1.5 space-y-1.5">
                {ev.system && (
                  <div>
                    <div className="text-[10px] font-bold text-[#8e8e93] mb-0.5">SYSTEM PROMPT</div>
                    <pre style={preBlock}>{ev.system}</pre>
                  </div>
                )}
                {ev.user && (
                  <div>
                    <div className="text-[10px] font-bold text-[#8e8e93] mb-0.5">USER</div>
                    <pre style={preBlock}>{ev.user}</pre>
                  </div>
                )}
                {ev.output && (
                  <div>
                    <div className="text-[10px] font-bold text-[#8e8e93] mb-0.5">LLM RESPONSE</div>
                    <pre style={preBlock}>{ev.output}</pre>
                  </div>
                )}
                {ev.sql && (
                  <div>
                    <div className="text-[10px] font-bold text-[#8e8e93] mb-0.5">
                      SQL {ev.params && ev.params.length ? `· params=${JSON.stringify(ev.params)}` : ""}
                    </div>
                    <pre style={preBlock}>{ev.sql}</pre>
                  </div>
                )}
              </div>
            </details>
          )}
        </div>
      </div>
    </div>
  );
}

function TracePanel({ events, streaming }: { events: TraceEvent[]; streaming?: boolean }) {
  const [open, setOpen] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [events.length, open]);

  return (
    <div className="mt-4 rounded-2xl" style={{ border: "1px solid #e5e5ea", background: "#fbfbfd" }}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-3.5 py-2.5 text-left"
      >
        <Bot size={14} style={{ color: "#3b4252" }} />
        <span className="text-[12.5px] font-semibold text-[#1c1c1e]">実行トレース（面接デモ用：LLM／SQL／ツール呼出）</span>
        <span className="text-[11px] text-[#8e8e93]">{events.length} ステップ</span>
        {streaming && (
          <span className="ml-1 inline-flex items-center gap-1.5 text-[11px] font-medium text-[#c06900]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#ff9500] animate-pulse" />
            実行中
          </span>
        )}
        <ChevronRight
          size={15}
          className="ml-auto text-[#8e8e93] transition-transform"
          style={{ transform: open ? "rotate(90deg)" : "none" }}
        />
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-1.5 max-h-[440px] overflow-y-auto">
          {events.map(ev => <TraceRow key={ev.key} ev={ev} />)}
          <div ref={endRef} />
        </div>
      )}
    </div>
  );
}

export default function ChatPanel() {
  const { activeMessages, activeSessionId, addMessage, patchMessage } = useChatContext();
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef  = useRef<HTMLInputElement>(null);
  const messages  = activeMessages;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  useEffect(() => {
    inputRef.current?.focus();
  }, [activeSessionId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const query = input.trim();
    const userMsg: Message = { id: `u-${Date.now()}`, role: "user", content: query };
    const assistantId = `a-${Date.now()}`;
    addMessage(userMsg);
    addMessage({ id: assistantId, role: "assistant", content: "", streaming: true, trace: [] });
    setInput("");
    setIsLoading(true);

    let keySeq = 0;
    const nextKey = (k: string) => `${k}-${Date.now()}-${keySeq++}`;
    const appendTrace = (te: Omit<TraceEvent, "key">) =>
      patchMessage(assistantId, m => ({
        ...m,
        trace: [...(m.trace ?? []), { ...te, key: nextKey(te.kind) }],
      }));
    const finishLLM = (label: string | undefined, patch: Partial<TraceEvent>) =>
      patchMessage(assistantId, m => {
        const trace = [...(m.trace ?? [])];
        for (let i = trace.length - 1; i >= 0; i--) {
          if (trace[i].kind === "llm" && trace[i].label === label && trace[i].pending) {
            trace[i] = { ...trace[i], ...patch, pending: false };
            break;
          }
        }
        return { ...m, trace };
      });

    const handleEvent = (name: string, evt: Record<string, unknown>) => {
      switch (name) {
        case "answer_delta":
          if (typeof evt.text === "string") {
            patchMessage(assistantId, m => ({ ...m, content: m.content + evt.text }));
          }
          break;
        case "cache":
          appendTrace({
            kind: "cache",
            hit: Boolean(evt.hit),
            reason: evt.reason as string,
            elapsed: evt.elapsed as number,
          });
          break;
        case "node":
          appendTrace({
            kind: "node",
            title: evt.title as string,
            detail: evt.detail as string,
            elapsed: evt.elapsed as number,
          });
          break;
        case "llm":
          if (evt.phase === "start") {
            appendTrace({
              kind: "llm",
              label: evt.label as string,
              phase: "start",
              model: evt.model as string,
              system: evt.system as string,
              user: evt.user as string,
              stream: Boolean(evt.stream),
              pending: true,
              elapsed: evt.elapsed as number,
            });
          } else if (evt.phase === "end") {
            finishLLM(evt.label as string, {
              output: evt.output as string,
              phase: "end",
              stream: Boolean(evt.stream),
            });
          } else {
            finishLLM(evt.label as string, { error: evt.error as string, pending: false });
          }
          break;
        case "sql":
          appendTrace({
            kind: "sql",
            table: evt.table as string,
            sql: evt.sql as string,
            params: evt.params as string[],
            rows: evt.rows as number,
            keyword: evt.keyword as string,
            elapsed: evt.elapsed as number,
          });
          break;
        case "tool":
          appendTrace({
            kind: "tool",
            tool: evt.tool as string,
            keyword: evt.keyword as string,
            rows: evt.rows as number,
            alerts: evt.alerts as number,
            error: evt.error as string | null,
            elapsed: evt.elapsed as number,
          });
          break;
        case "final": {
          const data = (evt.data ?? {}) as Partial<AskResponse>;
          patchMessage(assistantId, m => ({
            ...m,
            streaming: false,
            content: data.answer || m.content || "回答が生成されませんでした。もう一度お試しください。",
            citations: data.citations ?? [],
            evidenceScore: data.evidence_score,
            bestEvidenceScore: data.best_evidence_score,
            currentEvidenceScore: data.current_evidence_score,
            fromCache: data.from_cache ?? false,
            businessResult: data.business_result ?? null,
          }));
          break;
        }
        case "error":
          patchMessage(assistantId, m => ({
            ...m,
            streaming: false,
            isError: true,
            content: m.content || (evt.message as string) || "リクエストに失敗しました。",
          }));
          break;
        default:
          break;
      }
    };

    try {
      const res = await fetch(`${API_BASE_URL}/ask/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });

      if (!res.ok || !res.body) {
        throw new Error(`ストリーム接続に失敗しました（${res.status}）。`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sep: number;
        while ((sep = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          let eventName = "message";
          const dataLines: string[] = [];
          for (const line of frame.split("\n")) {
            if (line.startsWith("event:")) eventName = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
          if (!dataLines.length) continue;
          try {
            handleEvent(eventName, JSON.parse(dataLines.join("\n")));
          } catch {
            /* ignore malformed frame */
          }
        }
      }
    } catch (error) {
      patchMessage(assistantId, m => ({
        ...m,
        streaming: false,
        isError: true,
        content: m.content || buildErrorMessage(error),
      }));
    } finally {
      patchMessage(assistantId, m => ({ ...m, streaming: false }));
      setIsLoading(false);
    }
  };

  return (
    <section className="relative w-full flex flex-col items-center bg-[#f7f7f8] min-h-screen pb-40">

      {/* ── Chat Feed ─────────────────────────────────────── */}
      <div className="w-full max-w-2xl mx-auto px-4 pt-10 pb-6">
        <AnimatePresence mode="popLayout">

          {/* ── Empty State ─────────────────────────────────── */}
          {messages.length === 0 && !isLoading && (
            <motion.div
              key="empty"
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.97 }}
              transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
              className="flex flex-col items-center justify-center pt-12"
            >
              {/* Three.js Orb */}
              <div className="mb-6">
                <OrbCanvas size={148} isThinking={isLoading} />
              </div>

              <h2 className="text-[26px] font-semibold text-[#111113] tracking-tight mb-1.5">
                何をお手伝いしましょうか？
              </h2>
              <p className="text-[14px] text-[#a0a0ab] mb-10 text-center">
                商品カタログの検索、在庫・受注・入荷の照会、発注推奨まで対応します。
              </p>

              {/* Suggestion cards */}
              <div className="grid grid-cols-3 gap-2.5 w-full">
                {[
                  { title: "在庫照会", sub: "ステンレス鋼管 20A" },
                  { title: "商品仕様", sub: "ベアリング 6204ZZ" },
                  { title: "仕様と入荷", sub: "安全在庫・ベアリング" },
                ].map(({ title, sub }, i) => (
                  <button
                    key={i}
                    onClick={() => setInput(
                      i === 0 ? "ステンレス鋼管20Aの在庫はありますか？倉庫も教えてください。" :
                      i === 1 ? "ボールベアリング6204ZZの仕様と主な用途を教えてください。" :
                                "在庫が少ないベアリング6204ZZについて、仕様と入荷予定を教えてください。"
                    )}
                    className="text-left bg-white hover:bg-[#fafafa] rounded-2xl px-4 py-4 transition-all duration-200 cursor-pointer"
                    style={{
                      border: "1px solid rgba(0,0,0,0.08)",
                      boxShadow: "0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.03)",
                    }}
                  >
                    <p className="text-[13px] font-medium text-[#1c1c1e] leading-snug">{title}</p>
                    <p className="text-[12px] text-[#a0a0ab] mt-0.5">{sub}</p>
                  </button>
                ))}
              </div>
            </motion.div>
          )}

          {/* ── Message Thread ──────────────────────────────── */}
          {(messages.length > 0 || isLoading) && (
            <div className="space-y-8">
              {messages.filter(m =>
                m.content || m.streaming || (m.trace && m.trace.length > 0)
              ).map(msg => {
                const isAssistantError = msg.role === "assistant" && msg.isError;
                const hasResponseMeta =
                  !isAssistantError &&
                  !msg.streaming &&
                  !msg.businessResult &&
                  (
                    typeof msg.evidenceScore === "number" ||
                    typeof msg.bestEvidenceScore === "number" ||
                    typeof msg.currentEvidenceScore === "number" ||
                    typeof msg.fromCache === "boolean"
                  );
                const parsedCitations = (msg.citations ?? []).map(parseCitation);

                return (
                  <motion.div
                    key={msg.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
                    className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    {msg.role === "user" ? (
                      /* ── User Bubble ─── */
                      <div className="max-w-[75%] text-[#1c1c1e] text-[15px] leading-[1.65] px-5 py-3.5 rounded-[22px] rounded-tr-[6px]"
                        style={{
                          backgroundColor: "#f0f0f3",
                          border: "1px solid rgba(0,0,0,0.06)",
                        }}
                      >
                        {msg.content}
                      </div>
                    ) : (
                      /* ── Assistant Response ─── */
                      <div className="w-full">
                        <div className="flex items-start gap-3.5">
                          {/* mini orb */}
                          <div className="shrink-0 mt-1">
                            <OrbCanvas size={28} isThinking={false} />
                          </div>
                          {/* Markdown output */}
                          <div
                            className={`flex-1 text-[15px] text-[#1a1a1a] leading-[1.75] ${isAssistantError ? "rounded-[24px] px-5 py-4" : ""}`}
                            style={{
                              fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif',
                              ...(isAssistantError ? {
                                backgroundColor: "#fff7f7",
                                border: "1px solid #f3d6d8",
                              } : {}),
                            }}
                          >
                            {isAssistantError && (
                              <div
                                className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 mb-3 text-[11px] font-medium"
                                style={{
                                  backgroundColor: "#fff1f2",
                                  border: "1px solid #f5c2c7",
                                  color: "#b42318",
                                }}
                              >
                                <AlertCircle size={12} />
                                リクエスト失敗
                              </div>
                            )}

                            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                              {msg.content}
                            </ReactMarkdown>

                            {msg.streaming && (
                              <span
                                className="inline-block w-[7px] h-[15px] ml-1 align-text-bottom animate-pulse rounded-[1px]"
                                style={{ backgroundColor: "#c06900" }}
                              />
                            )}

                            {msg.businessResult && <BusinessCards data={msg.businessResult} />}

                            {msg.trace && msg.trace.length > 0 && (
                              <TracePanel events={msg.trace} streaming={msg.streaming} />
                            )}

                            {hasResponseMeta && (
                              <div className="flex flex-wrap gap-2 mt-4">
                                <div
                                  className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[11px] font-medium"
                                  style={{
                                    backgroundColor: msg.fromCache ? "#effaf4" : "#f4f6fb",
                                    border: `1px solid ${msg.fromCache ? "#cdebd8" : "#dce3f0"}`,
                                    color: msg.fromCache ? "#1f7a45" : "#52607a",
                                  }}
                                >
                                  <span
                                    className="w-1.5 h-1.5 rounded-full"
                                    style={{ backgroundColor: msg.fromCache ? "#1f7a45" : "#73839e" }}
                                  />
                                  {msg.fromCache ? "ウォームキャッシュ" : "新規取得"}
                                </div>

                                {[
                                  { label: "エビデンス", value: msg.evidenceScore },
                                  { label: "最高値", value: msg.bestEvidenceScore },
                                  { label: "現在値", value: msg.currentEvidenceScore },
                                ].map(({ label, value }) => (
                                  <div
                                    key={label}
                                    className="inline-flex items-center gap-2 rounded-full px-3 py-1.5"
                                    style={{
                                      backgroundColor: "#fbfbfc",
                                      border: "1px solid #ececef",
                                    }}
                                  >
                                    <span className="text-[10px] uppercase tracking-[0.12em] text-[#8e8e93]">{label}</span>
                                    <span className="text-[12px] font-semibold text-[#111113] tabular-nums">{formatScore(value)}</span>
                                  </div>
                                ))}
                              </div>
                            )}

                            {/* Citations */}
                            {parsedCitations.length > 0 && (
                              <div className="grid gap-2.5 mt-4 pt-3 sm:grid-cols-2" style={{ borderTop: "1px solid #f0f0f0" }}>
                                {parsedCitations.map((citation, i) => (
                                  <div
                                    key={`${citation.raw}-${i}`}
                                    className={`min-w-0 rounded-2xl px-3.5 py-3 transition-colors ${citation.sourceHref ? "cursor-pointer" : ""}`}
                                    style={{
                                      backgroundColor: "#fafafa",
                                      border: "1px solid #ececef",
                                    }}
                                    title={citation.fullPath}
                                    role={citation.sourceHref ? "link" : undefined}
                                    tabIndex={citation.sourceHref ? 0 : undefined}
                                    onClick={() => {
                                      if (citation.sourceHref) {
                                        window.open(citation.sourceHref, "_blank", "noopener,noreferrer");
                                      }
                                    }}
                                    onKeyDown={(event) => {
                                      if (!citation.sourceHref) return;
                                      if (event.key === "Enter" || event.key === " ") {
                                        event.preventDefault();
                                        window.open(citation.sourceHref, "_blank", "noopener,noreferrer");
                                      }
                                    }}
                                  >
                                    <div className="flex items-start justify-between gap-3">
                                      <div className="min-w-0 flex-1">
                                        <div className="flex items-center gap-2 min-w-0">
                                          <span className="truncate text-[12px] font-semibold text-[#1c1c1e]">
                                            {citation.filename}
                                          </span>
                                          {citation.isWebSearch && (
                                            <span
                                              className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]"
                                              style={{
                                                backgroundColor: "#fff4e8",
                                                border: "1px solid #f2d2a6",
                                                color: "#9a5d12",
                                              }}
                                            >
                                              Web
                                            </span>
                                          )}
                                          {citation.isBusiness && (
                                            <span
                                              className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]"
                                              style={{
                                                backgroundColor: "#eef2ff",
                                                border: "1px solid #c7d2fe",
                                                color: "#3730a3",
                                              }}
                                            >
                                              DB
                                            </span>
                                          )}
                                        </div>
                                        <div className="mt-1 truncate font-mono text-[11px] text-[#8e8e93]">
                                          {citation.compactPath}
                                        </div>
                                      </div>

                                      <div className="flex items-center gap-1.5 shrink-0">
                                        {citation.sourceHref && (
                                          <a
                                            href={citation.sourceHref}
                                            target="_blank"
                                            rel="noreferrer"
                                            onClick={(event) => event.stopPropagation()}
                                            className="inline-flex items-center justify-center w-8 h-8 rounded-xl transition-colors"
                                            style={{
                                              backgroundColor: "#ffffff",
                                              border: "1px solid #e5e5e7",
                                              color: "#6e6e80",
                                            }}
                                            title={citation.isWebSearch ? "リンクを開く" : "GitHubでソースを開く"}
                                          >
                                            <ExternalLink size={14} />
                                          </a>
                                        )}
                                        {citation.downloadHref && (
                                          <a
                                            href={citation.downloadHref}
                                            onClick={(event) => event.stopPropagation()}
                                            className="inline-flex items-center justify-center w-8 h-8 rounded-xl transition-colors"
                                            style={{
                                              backgroundColor: "#ffffff",
                                              border: "1px solid #e5e5e7",
                                              color: "#6e6e80",
                                            }}
                                            title="ソースファイルをダウンロード"
                                          >
                                            <Download size={14} />
                                          </a>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    )}
                  </motion.div>
                );
              })}

              {/* Thinking indicator (only when no streaming assistant bubble yet) */}
              {isLoading && !messages.some(m => m.streaming) && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="flex items-center gap-3.5"
                >
                  <div className="shrink-0">
                    <OrbCanvas size={28} isThinking={true} />
                  </div>
                  <div className="flex gap-1 items-center">
                    {[0,1,2].map(i => (
                      <div
                        key={i}
                        className="w-1.5 h-1.5 rounded-full"
                        style={{
                          backgroundColor: "#c7c7cc",
                          animation: `orbPulse 1.1s ease-in-out ${i * 0.18}s infinite`,
                        }}
                      />
                    ))}
                  </div>
                </motion.div>
              )}
            </div>
          )}
        </AnimatePresence>
        <div ref={bottomRef} />
      </div>

      {/* ── Fixed Input Bar ─────────────────────────────────── */}
      <div className="fixed bottom-0 inset-x-0 flex flex-col items-center px-4 pb-5 pt-6 bg-gradient-to-t from-[#f7f7f8] via-[#f7f7f8]/90 to-transparent z-50">
        <form
          onSubmit={handleSubmit}
          className="relative w-full max-w-2xl bg-white rounded-[20px] transition-all"
          style={{
            border: "1px solid rgba(0,0,0,0.09)",
            boxShadow: "0 2px 8px rgba(0,0,0,0.05), 0 8px 28px rgba(0,0,0,0.04)",
          }}
        >
          <input
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="商品名・品番・受注番号、または仕様を入力してください…"
            className="w-full bg-transparent text-[15px] text-[#1c1c1e] placeholder-[#a0a0ab] px-5 py-[17px] pr-16 focus:outline-none rounded-[20px]"
            disabled={isLoading}
            onKeyDown={e => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e as unknown as React.FormEvent);
              }
            }}
          />
          <button
            type="submit"
            disabled={!input.trim() || isLoading}
            className="absolute right-3 top-1/2 -translate-y-1/2 w-9 h-9 rounded-xl flex items-center justify-center text-white transition-all cursor-pointer disabled:cursor-not-allowed"
            style={{ backgroundColor: !input.trim() || isLoading ? "#d1d1d6" : "#0d0d0d" }}
          >
            <ArrowUp size={16} strokeWidth={2.5} />
          </button>
        </form>

        {/* AI Disclaimer */}
        <p className="mt-2.5 text-[11px] text-[#c7c7cc] text-center">
          在庫・受注・入荷データはデモ用の模擬データです。重要な発注判断は実システムでご確認ください。
        </p>
      </div>
    </section>
  );
}
