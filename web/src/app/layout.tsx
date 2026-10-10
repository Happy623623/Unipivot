import type { Metadata } from "next";
import { Inter, Noto_Sans_KR } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";

// Figma CDN 글꼴 대신 next/font로 직접 불러온다. 둘 다 가변 글꼴이라 굵기 지정이 필요 없다.
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const notoSansKr = Noto_Sans_KR({ preload: false, variable: "--font-noto-kr", display: "swap" });

export const metadata: Metadata = {
  title: "UNIPIVOT",
  description: "지원할 수 있는 장학금·정책·공모전을 찾아 준비 일정까지 만들어요",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko" className={`${inter.variable} ${notoSansKr.variable}`}>
      <body>{children}</body>
    </html>
  );
}
