"use client";

import { createContext, useContext, useState, useCallback, useEffect } from "react";

export interface TraceEvent {
  key: string;
  kind: "node" | "llm" | "sql" | "tool" | "cache" | "info";
  elapsed?: number;
  // node / cache
  title?: string;
  detail?: string;
  hit?: boolean;
  reason?: string;
  // llm
  label?: string;
  phase?: string;
  model?: string;
  system?: string;
  user?: string;
  output?: string;
  stream?: boolean;
  pending?: boolean;
  // sql / tool
  table?: string;
  sql?: string;
  params?: string[];
  rows?: number;
  keyword?: string;
  tool?: string;
  alerts?: number;
  error?: string | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: string[];
  evidenceScore?: number;
  bestEvidenceScore?: number;
  currentEvidenceScore?: number;
  fromCache?: boolean;
  isError?: boolean;
  businessResult?: BusinessResult | null;
  streaming?: boolean;
  trace?: TraceEvent[];
}

export interface StockRow {
  product_code: string;
  name: string;
  category?: string;
  spec?: string;
  unit?: string;
  price_jpy?: number;
  stock_qty: number;
  safety_stock: number;
  warehouse?: string;
  status: string;
}

export interface OrderRow {
  order_no: string;
  customer?: string;
  product_code?: string;
  product_name?: string;
  qty?: number;
  unit?: string;
  status?: string;
  order_date?: string;
  due_date?: string;
}

export interface ShipmentRow {
  shipment_no: string;
  product_code?: string;
  product_name?: string;
  direction?: string;
  qty?: number;
  unit?: string;
  status?: string;
  date_or_eta?: string;
  warehouse?: string;
}

export interface AlertRow {
  product_code: string;
  name: string;
  stock_qty: number;
  safety_stock: number;
  unit?: string;
  suggested_purchase_qty: number;
  reason: string;
}

export interface BusinessResult {
  stock: StockRow[];
  orders: OrderRow[];
  shipments: ShipmentRow[];
  alerts: AlertRow[];
}

export interface Session {
  id: string;
  title: string;
  messages: Message[];
  createdAt: Date;
}

interface ChatContextType {
  sessions: Session[];
  activeSessionId: string | null;
  activeMessages: Message[];
  startNewSession: () => void;
  loadSession: (id: string) => void;
  deleteSession: (id: string) => void;
  addMessage: (msg: Message) => void;
  updateLastAssistantMessage: (
    content: string,
    citations?: string[],
    metadata?: Partial<Message>,
  ) => void;
  patchMessage: (id: string, updater: (m: Message) => Message) => void;
}

const ChatContext = createContext<ChatContextType | null>(null);

interface ChatState {
  sessions: Session[];
  activeSessionId: string | null;
}

// ── localStorage persistence ─────────────────────────────────────────────────
// Demo 用：会话历史保存在浏览器本地（无需后端）。刷新/重开页面后仍可查看并继续。
const STORAGE_KEY = "trade_knowledge_sessions_v1";
const MAX_SESSIONS = 24;

function loadInitialState(): ChatState {
  if (typeof window === "undefined") return { sessions: [], activeSessionId: null };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { sessions: [], activeSessionId: null };
    const parsed = JSON.parse(raw) as { sessions?: Session[]; activeSessionId?: string | null };
    const sessions = (parsed.sessions ?? []).map((s) => ({
      ...s,
      createdAt: new Date(s.createdAt),
      // 刷新后任何"正在生成"的消息都应停止，避免一直停在実行中。
      messages: (s.messages ?? []).map((m) => ({ ...m, streaming: false })),
    }));
    // 启动时不自动选中会话，落在欢迎页；用户从履歴里选择。
    return { sessions, activeSessionId: null };
  } catch {
    return { sessions: [], activeSessionId: null };
  }
}

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<ChatState>(loadInitialState);

  const activeSession = state.sessions.find(s => s.id === state.activeSessionId) ?? null;
  const activeMessages = activeSession?.messages ?? [];

  // Persist on every change (new message / switch / delete).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const persist = (sessions: Session[], activeSessionId: string | null) => {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ sessions, activeSessionId }),
      );
    };
    try {
      persist(state.sessions.slice(0, MAX_SESSIONS), state.activeSessionId);
    } catch {
      // Quota exceeded (full traces can be large): keep only the most recent.
      try {
        persist(state.sessions.slice(0, 8), state.activeSessionId);
      } catch {
        /* storage unavailable — ignore */
      }
    }
  }, [state]);

  const startNewSession = useCallback(() => {
    setState(prev => ({ ...prev, activeSessionId: null }));
  }, []);

  const loadSession = useCallback((id: string) => {
    setState(prev => ({ ...prev, activeSessionId: id }));
  }, []);

  const deleteSession = useCallback((id: string) => {
    setState(prev => ({
      sessions: prev.sessions.filter(s => s.id !== id),
      activeSessionId: prev.activeSessionId === id ? null : prev.activeSessionId,
    }));
  }, []);

  const addMessage = useCallback((msg: Message) => {
    setState(prev => {
      // If no active session, create one
      if (!prev.activeSessionId) {
        const newSession: Session = {
          id: Date.now().toString(),
          title: msg.content.length > 48 ? msg.content.slice(0, 48) + "…" : msg.content,
          messages: [msg],
          createdAt: new Date(),
        };
        return {
          sessions: [newSession, ...prev.sessions],
          activeSessionId: newSession.id,
        };
      }

      // Otherwise append to active session
      return {
        ...prev,
        sessions: prev.sessions.map(s =>
          s.id === prev.activeSessionId
            ? { ...s, messages: [...s.messages, msg] }
            : s
        ),
      };
    });
  }, []);

  const updateLastAssistantMessage = useCallback((
    content: string,
    citations?: string[],
    metadata?: Partial<Message>,
  ) => {
    setState(prev => ({
      ...prev,
      sessions: prev.sessions.map(s => {
        if (s.id !== prev.activeSessionId) return s;
        const msgs = [...s.messages];
        const lastIdx = msgs.length - 1;
        if (lastIdx >= 0 && msgs[lastIdx].role === "assistant") {
          msgs[lastIdx] = { ...msgs[lastIdx], content, citations, ...metadata };
        }
        return { ...s, messages: msgs };
      }),
    }));
  }, []);

  const patchMessage = useCallback((id: string, updater: (m: Message) => Message) => {
    setState(prev => ({
      ...prev,
      sessions: prev.sessions.map(s =>
        s.messages.some(m => m.id === id)
          ? { ...s, messages: s.messages.map(m => (m.id === id ? updater(m) : m)) }
          : s
      ),
    }));
  }, []);

  return (
    <ChatContext.Provider value={{
      sessions: state.sessions,
      activeSessionId: state.activeSessionId,
      activeMessages,
      startNewSession,
      loadSession,
      deleteSession,
      addMessage,
      updateLastAssistantMessage,
      patchMessage,
    }}>
      {children}
    </ChatContext.Provider>
  );
}

export function useChatContext() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChatContext must be used within ChatProvider");
  return ctx;
}
