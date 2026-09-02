import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Thư viện hỏi đáp",
  description: "Hỏi đáp tài liệu trong thư viện bằng AI",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
