"use client";

import { ChatProvider } from "@/context/ChatContext";
import Sidebar from "@/components/Sidebar";
import ChatPanel from "@/components/ChatPanel";

export default function Home() {
  return (
    <ChatProvider>
      <main className="flex w-full min-h-screen text-[#0d0d0d] bg-[#f7f7f8]">
        <Sidebar />
        <ChatPanel />
      </main>
    </ChatProvider>
  );
}
