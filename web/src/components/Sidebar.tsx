"use client";

import { useState } from "react";
import { SquarePen, History } from "lucide-react";
import { useChatContext } from "@/context/ChatContext";
import HistoryPanel from "@/components/HistoryPanel";

export default function Sidebar() {
  const { startNewSession } = useChatContext();
  const [historyOpen, setHistoryOpen] = useState(false);

  return (
    <>
      <aside
        className="fixed left-4 top-1/2 z-30 flex flex-col items-center gap-3 py-5 px-2.5"
        style={{
          transform: "translateY(-50%)",
          background: "rgba(255,255,255,0.82)",
          backdropFilter: "blur(24px) saturate(1.6)",
          WebkitBackdropFilter: "blur(24px) saturate(1.6)",
          border: "1px solid rgba(0,0,0,0.07)",
          borderRadius: 999,
          boxShadow: "0 2px 4px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.06), inset 0 1px 0 rgba(255,255,255,0.9)",
        }}
      >
        <button
          onClick={() => startNewSession()}
          title="新しいチャット"
          className="w-9 h-9 rounded-full flex items-center justify-center text-[#6e6e80] hover:bg-black/5 hover:text-[#0d0d0d] transition-all duration-200 cursor-pointer"
        >
          <SquarePen size={17} strokeWidth={1.8} />
        </button>

        <div
          className="w-5 h-px"
          style={{ backgroundColor: "rgba(0,0,0,0.08)" }}
        />

        <button
          onClick={() => setHistoryOpen(true)}
          title="会話履歴"
          className="w-9 h-9 rounded-full flex items-center justify-center text-[#6e6e80] hover:bg-black/5 hover:text-[#0d0d0d] transition-all duration-200 cursor-pointer"
        >
          <History size={17} strokeWidth={1.8} />
        </button>
      </aside>

      <HistoryPanel open={historyOpen} onClose={() => setHistoryOpen(false)} />
    </>
  );
}
