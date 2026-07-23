import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Digital Worker Platform",
  description:
    "Multi-tenant Digital Worker platform — tender & work operations",
};

const NAV_ITEMS: Array<{ href: string; label: string }> = [
  { href: "/home", label: "Home" },
  { href: "/inbox", label: "Inbox" },
  { href: "/approvals", label: "Approvals" },
  { href: "/procurement", label: "Procurement" },
  { href: "/work-ops", label: "Work Ops" },
  { href: "/knowledge", label: "Knowledge" },
  { href: "/memory", label: "Memory" },
  { href: "/integrations", label: "Integrations" },
  { href: "/audit", label: "Audit" },
  { href: "/admin", label: "Admin" },
];

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="vi">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased dark:bg-slate-950 dark:text-slate-100">
        <div className="flex min-h-screen">
          <aside className="w-56 shrink-0 border-r border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <Link href="/home" className="mb-6 block text-lg font-bold">
              Digital Worker
            </Link>
            <nav aria-label="Main navigation" className="space-y-1">
              {NAV_ITEMS.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="block rounded-md px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </aside>
          <main className="flex-1 p-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
