"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowLeft, type LucideIcon } from "lucide-react";
import { cn } from "@dw/ui";
import { SessionChip } from "./session-chip";

export interface AreaNavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  exact?: boolean;
}

/** Per-module shell: focused sidebar + header. One module, one flow. */
export function AreaShell({
  title,
  icon: Icon,
  items,
  children,
}: {
  title: string;
  icon: LucideIcon;
  items: AreaNavItem[];
  children: ReactNode;
}) {
  const pathname = usePathname();
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r bg-sidebar px-3 py-4 md:flex">
        <div className="mb-6 flex items-center gap-2 px-2 text-base font-semibold">
          <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Icon className="size-5" />
          </span>
          {title}
        </div>
        <nav className="flex flex-1 flex-col gap-0.5">
          {items.map((item) => {
            const active = item.exact
              ? pathname === item.href
              : pathname === item.href || pathname.startsWith(item.href + "/");
            const ItemIcon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-2 py-2 text-sm transition-colors",
                  active
                    ? "bg-sidebar-accent font-medium"
                    : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
                )}
              >
                <ItemIcon className="size-4 shrink-0" />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <Link
          href="/"
          className="flex items-center gap-2 rounded-md px-2 py-2 text-xs text-muted-foreground transition-colors hover:bg-sidebar-accent/60 hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          Về trang chọn module
        </Link>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-14 items-center justify-end border-b bg-background/80 px-6 backdrop-blur">
          <SessionChip />
        </header>
        <main className="flex-1 p-6 md:p-8">{children}</main>
      </div>
    </div>
  );
}
