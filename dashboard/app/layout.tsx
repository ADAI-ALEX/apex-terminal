import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Apex Algo — Command Centre",
  description: "Real-time monitoring for the Apex spread-betting algorithm.",
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
