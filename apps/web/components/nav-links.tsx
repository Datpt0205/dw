"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BadgeCheck,
  FileSearch,
  LayoutDashboard,
  Library,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@dw/ui";
import { useAuth } from "../lib/auth/auth-context";

interface NavItem {
  href: string;
  label: string;
  hint: string;
  icon: LucideIcon;
  exact?: boolean;
  section: string;
  /** Scope required to see this item (omit = always visible). */
  scope?: string;
}

const ITEMS: NavItem[] = [
  {
    href: "/",
    label: "Tổng quan",
    hint: "Tổng quan vận hành",
    icon: LayoutDashboard,
    exact: true,
    section: "Tổng quan",
  },
  {
    href: "/procurement/dw01",
    label: "Quản lý gói thầu",
    hint: "DW01 — phân loại và chuẩn bị hồ sơ mời thầu",
    icon: FileSearch,
    scope: "tender.read",
    section: "Nghiệp vụ",
  },
  {
    href: "/knowledge",
    label: "Tri thức",
    hint: "Luật, quy chế và biểu mẫu tham chiếu",
    icon: Library,
    scope: "knowledge.read",
    section: "Tài nguyên",
  },
  {
    href: "/approvals",
    label: "Phê duyệt",
    hint: "Duyệt đề xuất & giao việc",
    icon: BadgeCheck,
    scope: "approvals.decide",
    section: "Tài nguyên",
  },
];

export function NavLinks({ mobile = false }: { mobile?: boolean }) {
  const pathname = usePathname();
  const { hasScope } = useAuth();
  const visible = ITEMS.filter((item) => !item.scope || hasScope(item.scope));
  return (
    <nav
      aria-label="Main navigation"
      className={
        mobile ? "flex min-w-max items-center gap-1" : "flex flex-col gap-1"
      }
    >
      {visible.map((item, index) => {
        const active = item.exact
          ? pathname === item.href
          : pathname === item.href || pathname.startsWith(item.href + "/");
        const Icon = item.icon;
        const showSection =
          !mobile &&
          (index === 0 || visible[index - 1]?.section !== item.section);
        return (
          <div key={item.href}>
            {showSection && (
              <p className="mb-1 mt-5 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/70 first:mt-0">
                {item.section}
              </p>
            )}
            <Link
              href={item.href}
              title={item.hint}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm transition-colors",
                active
                  ? "bg-primary font-semibold text-white shadow-sm"
                  : "text-slate-600 hover:bg-sidebar-accent hover:text-foreground",
              )}
            >
              <Icon className="size-4 shrink-0" />
              {item.label}
            </Link>
          </div>
        );
      })}
    </nav>
  );
}
