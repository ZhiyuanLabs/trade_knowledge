import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const interFont = Inter({
  subsets: ["latin"],
  variable: "--font-geist-sans",
});

export const metadata: Metadata = {
  title: "trade_knowledge",
  description: "日本総合商社向けの商品カタログRAGと在庫・受注・物流照会を行うAgentic RAG業務アシスタント。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja">
      <body className={`${interFont.variable} antialiased`}>
        {children}
      </body>
    </html>
  );
}
