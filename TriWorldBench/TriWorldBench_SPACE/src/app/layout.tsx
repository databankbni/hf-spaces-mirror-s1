import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TriWorldBench",
  description:
    "A multi-view robotic world-model video evaluation challenge for physical plausibility, cross-view consistency, and language-action alignment.",
  icons: {
    icon: "/assets_common/photos/image_155613883779109.png",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" data-twb-lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
