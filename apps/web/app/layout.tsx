import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import { Bot } from "lucide-react";
import { Toaster } from "sonner";
import { NavLinks } from "../components/nav-links";
import { SessionChip } from "../components/session-chip";
import "./globals.css";

export const metadata: Metadata = {
  title: "Digital Worker Platform",
  description:
    "Multi-tenant Digital Worker platform — tender & work operations",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="vi">
      <body className="min-h-screen antialiased">
        <div className="flex min-h-screen">
          <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r bg-sidebar px-3 py-4 text-sidebar-foreground md:flex">
            <Link
              href="/home"
              className="mb-6 flex items-center gap-2 px-2 text-base font-semibold"
            >
              <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <Bot className="size-5" />
              </span>
              Digital Worker
            </Link>
            <div className="flex-1 overflow-y-auto">
              <NavLinks />
            </div>
          </aside>
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-10 flex h-14 items-center justify-end border-b bg-background/80 px-6 backdrop-blur">
              <SessionChip />
            </header>
            <main className="flex-1 p-6 md:p-8">{children}</main>
          </div>
        </div>
        <Toaster richColors position="bottom-right" />
      </body>
    </html>
  );
}
