"use client";

import { motion, AnimatePresence } from "framer-motion";
import { History, MessageSquare, SquarePen, Trash2, X } from "lucide-react";
import { useChatContext } from "@/context/ChatContext";

function formatTime(d: Date): string {
  const date = new Date(d);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday = date.toDateString() === yesterday.toDateString();
  if (sameDay) {
    return date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
  }
  if (isYesterday) return "昨日";
  return date.toLocaleDateString("ja-JP", { month: "2-digit", day: "2-digit" });
}

export default function HistoryPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { sessions, activeSessionId, loadSession, startNewSession, deleteSession } =
    useChatContext();

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            className="fixed inset-0 z-40"
            style={{ backgroundColor: "rgba(0,0,0,0.18)" }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
          />

          {/* Drawer */}
          <motion.aside
            initial={{ x: -320 }}
            animate={{ x: 0 }}
            exit={{ x: -320 }}
            transition={{ type: "spring", stiffness: 320, damping: 34 }}
            className="fixed left-0 top-0 bottom-0 z-50 w-[320px] flex flex-col"
            style={{
              background: "rgba(255,255,255,0.92)",
              backdropFilter: "blur(28px) saturate(1.6)",
              WebkitBackdropFilter: "blur(28px) saturate(1.6)",
              borderRight: "1px solid rgba(0,0,0,0.08)",
              boxShadow: "8px 0 40px rgba(0,0,0,0.08)",
            }}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 pt-6 pb-3">
              <div className="flex items-center gap-2">
                <History size={16} style={{ color: "#1c1c1e" }} />
                <h2 className="text-[15px] font-semibold text-[#1c1c1e]">会話履歴</h2>
              </div>
              <button
                onClick={onClose}
                title="閉じる"
                className="w-8 h-8 rounded-full flex items-center justify-center text-[#6e6e80] hover:bg-black/5 hover:text-[#0d0d0d] transition-all cursor-pointer"
              >
                <X size={16} strokeWidth={1.8} />
              </button>
            </div>

            {/* New chat */}
            <div className="px-3 pb-3">
              <button
                onClick={() => {
                  startNewSession();
                  onClose();
                }}
                className="w-full flex items-center gap-2 rounded-xl px-3.5 py-2.5 text-[13px] font-medium text-white transition-all cursor-pointer"
                style={{ backgroundColor: "#0d0d0d" }}
              >
                <SquarePen size={15} strokeWidth={1.9} />
                新しいチャット
              </button>
            </div>

            {/* Session list */}
            <div className="flex-1 overflow-y-auto px-3 pb-4 space-y-1">
              {sessions.length === 0 ? (
                <div className="flex flex-col items-center text-center mt-12 px-6">
                  <MessageSquare size={26} className="text-[#d1d1d6] mb-3" />
                  <p className="text-[12.5px] text-[#a0a0ab] leading-relaxed">
                    保存された会話はありません。
                    <br />
                    質問すると、ここに履歴が自動で保存されます。
                  </p>
                </div>
              ) : (
                sessions.map((s) => {
                  const active = s.id === activeSessionId;
                  const questionCount = s.messages.filter((m) => m.role === "user").length;
                  return (
                    <div
                      key={s.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => {
                        loadSession(s.id);
                        onClose();
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          loadSession(s.id);
                          onClose();
                        }
                      }}
                      className="group flex items-center gap-2.5 rounded-xl px-3 py-2.5 cursor-pointer transition-colors"
                      style={{
                        backgroundColor: active ? "rgba(0,0,0,0.06)" : "transparent",
                      }}
                      onMouseEnter={(e) => {
                        if (!active) e.currentTarget.style.backgroundColor = "rgba(0,0,0,0.035)";
                      }}
                      onMouseLeave={(e) => {
                        if (!active) e.currentTarget.style.backgroundColor = "transparent";
                      }}
                    >
                      <MessageSquare size={15} className="shrink-0 text-[#8e8e93]" />
                      <div className="min-w-0 flex-1">
                        <div className="text-[13px] font-medium text-[#1c1c1e] truncate leading-snug">
                          {s.title || "（無題）"}
                        </div>
                        <div className="text-[11px] text-[#a0a0ab] mt-0.5">
                          {formatTime(s.createdAt)}
                          {questionCount > 0 ? ` ・ ${questionCount} 問` : ""}
                        </div>
                      </div>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          deleteSession(s.id);
                        }}
                        title="この会話を削除"
                        className="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center text-[#a0a0ab] opacity-0 group-hover:opacity-100 hover:text-[#d70015] hover:bg-red-50 transition-all cursor-pointer"
                      >
                        <Trash2 size={13.5} />
                      </button>
                    </div>
                  );
                })
              )}
            </div>

            {/* Footer note */}
            <div className="px-5 py-3" style={{ borderTop: "1px solid rgba(0,0,0,0.06)" }}>
              <p className="text-[10.5px] text-[#b0b0b7] leading-relaxed">
                履歴はこのブラウザにローカル保存されます（デモ用）。
              </p>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
