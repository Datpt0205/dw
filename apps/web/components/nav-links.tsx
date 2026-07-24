"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BadgeCheck, FileSearch, Home, type LucideIcon } from "lucide-react";
import { cn } from "@dw/ui";
import { useAuth } from "../lib/auth/auth-context";

interface NavItem {
  href: string;
  label: string;
  hint: string;
  icon: LucideIcon;
  exact?: boolean;
  /** Scope required to see this item (omit = always visible). */
  scope?: string;
}

const ITEMS: NavItem[] = [
  {
    href: "/",
    label: "Trang chủ",
    hint: "Tổng quan",
    icon: Home,
    exact: true,
  },
  {
    href: "/procurement/dw01",
    label: "Xây hồ sơ thầu",
    hint: "DW01 — chuẩn bị hồ sơ mời thầu",
    icon: FileSearch,
    scope: "tender.read",
  },
  {
    href: "/approvals",
    label: "Phê duyệt",
    hint: "Duyệt đề xuất & giao việc",
    icon: BadgeCheck,
    scope: "approvals.decide",
  },
];

export function NavLinks() {
  const pathname = usePathname();
  const { hasScope } = useAuth();
  const visible = ITEMS.filter((item) => !item.scope || hasScope(item.scope));
  return (
    <nav aria-label="Main navigation" className="flex flex-col gap-1">
      {visible.map((item) => {
        const active = item.exact
          ? pathname === item.href
          : pathname === item.href || pathname.startsWith(item.href + "/");
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            title={item.hint}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-2 py-2 text-sm transition-colors",
              active
                ? "bg-sidebar-accent font-medium"
                : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
            )}
          >
            <Icon className="size-4 shrink-0" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
