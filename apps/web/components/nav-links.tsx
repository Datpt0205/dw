"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BadgeCheck,
  ClipboardList,
  FileSearch,
  Home,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@dw/ui";

interface NavItem {
  href: string;
  label: string;
  hint: string;
  icon: LucideIcon;
  exact?: boolean;
}

const ITEMS: NavItem[] = [
  {
    href: "/",
    label: "Trang chủ",
    hint: "Đăng nhập & bắt đầu",
    icon: Home,
    exact: true,
  },
  {
    href: "/tender",
    label: "Đấu thầu",
    hint: "Phân tích hồ sơ thầu",
    icon: FileSearch,
  },
  {
    href: "/meetings",
    label: "Cuộc họp",
    hint: "Họp → action item",
    icon: ClipboardList,
  },
  {
    href: "/approvals",
    label: "Phê duyệt",
    hint: "Duyệt đề xuất & giao việc",
    icon: BadgeCheck,
  },
];

export function NavLinks() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main navigation" className="flex flex-col gap-1">
      {ITEMS.map((item) => {
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
