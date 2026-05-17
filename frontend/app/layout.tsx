import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Digital Transformation Platform",
  description: "CRM MVP",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
