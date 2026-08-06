import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import Navigation from "@/src/components/Navigation";
import Footer from "@/src/components/Footer";
import { hasNews } from "@/src/content/news";
import { getConsoleUrl } from "@/src/config/console";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "TS-Arena",
  description: "Time Series Forecasting Arena - Browse challenges and visualize time series data",
  icons: {
    icon: '/rocket.svg',
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const consoleUrl = getConsoleUrl();

  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased flex flex-col min-h-screen`}
      >
        <Navigation showNews={hasNews()} consoleUrl={consoleUrl} />
        <main className="flex-1">
          {children}
        </main>
        <Footer consoleUrl={consoleUrl} />
        {/* Self-hosted Umami on franzia. data-domains is an allowlist: any other
            host serving this build (the Hugging Face Space mirror, a local dev
            server) loads the script but reports nothing. */}
        <script
          defer
          src="https://edge.ts-arena.live/t.js"
          data-website-id="cc85b0fc-786f-44ec-8445-b4ee463f63f6"
          data-domains="ts-arena.live"
        />
      </body>
    </html>
  );
}
