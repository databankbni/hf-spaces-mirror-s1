import type { Metadata } from "next";
import "@/styles/triworldbench.css";

export const metadata: Metadata = {
  title: "TriWorldBench",
};

export default function TriWorldLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
