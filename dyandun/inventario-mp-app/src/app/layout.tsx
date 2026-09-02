import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Inventario MP Nacional",
  description: "Gestión de almacenamiento, calidad y movimientos de materia prima."
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
