import type { Metadata } from "next";
import { Geist, Geist_Mono, Syne } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ProgressBarProvider } from "@/components/providers/ProgressBarProvider";
import { QueryProvider } from "@/components/providers/QueryProvider";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const syne = Syne({
  variable: "--font-syne",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
});

export const metadata: Metadata = {
  title: "ChemAgent",
  description: "AI Chemistry Expert",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className={`${geistSans.variable} ${geistMono.variable} ${syne.variable} antialiased`}>
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false}>
          <QueryProvider>
            <ProgressBarProvider>
              <TooltipProvider>{children}</TooltipProvider>
            </ProgressBarProvider>
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
