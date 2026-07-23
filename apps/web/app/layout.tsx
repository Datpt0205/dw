import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import { Bot } from "lucide-react";
import { Toaster } from "sonner";
import { AssistantChat } from "../components/assistant-chat";
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
      <body className="min-h-screen bg-background antialiased">
        <div className="flex min-h-screen">
          <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r bg-sidebar px-3 py-4 md:flex">
            <Link
              href="/"
              className="mb-6 flex items-center gap-2 px-2 text-base font-semibold"
            >
              <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <Bot className="size-5" />
              </span>
              Digital Worker
            </Link>
            <div className="flex-1">
              <NavLinks />
            </div>
            <p className="px-2 text-[10px] leading-relaxed text-muted-foreground/70">
              Hệ thống:{" "}
              <Link className="underline" href="/audit">
                Nhật ký
              </Link>{" "}
              ·{" "}
              <Link className="underline" href="/admin">
                Admin
              </Link>
            </p>
          </aside>
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-10 flex h-14 items-center justify-end border-b bg-background/80 px-6 backdrop-blur">
              <SessionChip />
            </header>
            <main className="flex-1 p-6 md:p-8">{children}</main>
          </div>
        </div>
        <AssistantChat />
        <Toaster richColors position="bottom-right" />
      </body>
    </html>
  );
}
