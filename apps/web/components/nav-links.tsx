"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BadgeCheck,
  BookOpen,
  Brain,
  ClipboardList,
  FileSearch,
  Home,
  Inbox,
  Plug,
  ScrollText,
  Settings,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@dw/ui";

interface NavItem {
  href: string;
  label: string;
  hint: string;
  icon: LucideIcon;
}

const GROUPS: Array<{ title: string; items: NavItem[] }> = [
  {
    title: "Làm việc",
    items: [
      {
        href: "/home",
        label: "Trang chủ",
        hint: "Luồng demo từng bước",
        icon: Home,
      },
      {
        href: "/inbox",
        label: "Hộp việc",
        hint: "Việc đang chờ bạn",
        icon: Inbox,
      },
      {
        href: "/approvals",
        label: "Phê duyệt",
        hint: "Duyệt / từ chối đề xuất",
        icon: BadgeCheck,
      },
    ],
  },
  {
    title: "Nghiệp vụ",
    items: [
      {
        href: "/procurement",
        label: "Mua sắm / Thầu",
        hint: "Phân tích hồ sơ thầu",
        icon: FileSearch,
      },
      {
        href: "/work-ops",
        label: "Vận hành họp",
        hint: "Họp → action item",
        icon: ClipboardList,
      },
    ],
  },
  {
    title: "Nền tảng",
    items: [
      {
        href: "/knowledge",
        label: "Tri thức",
        hint: "Tài liệu đã ingest",
        icon: BookOpen,
      },
      {
        href: "/memory",
        label: "Trí nhớ",
        hint: "Fact máy ghi nhớ",
        icon: Brain,
      },
      {
        href: "/integrations",
        label: "Tích hợp",
        hint: "Tool + policy",
        icon: Plug,
      },
      {
        href: "/audit",
        label: "Nhật ký",
        hint: "Audit bất biến",
        icon: ScrollText,
      },
    ],
  },
  {
    title: "Hệ thống",
    items: [
      {
        href: "/admin",
        label: "Đăng nhập",
        hint: "Chọn nhân vật demo",
        icon: Settings,
      },
    ],
  },
];

export function NavLinks() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main navigation" className="flex flex-col gap-5">
      {GROUPS.map((group) => (
        <div key={group.title}>
          <p className="px-2 pb-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
            {group.title}
          </p>
          <div className="flex flex-col gap-0.5">
            {group.items.map((item) => {
              const active =
                pathname === item.href || pathname.startsWith(item.href + "/");
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  title={item.hint}
                  className={cn(
                    "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
                    active
                      ? "bg-sidebar-accent font-medium text-sidebar-foreground"
                      : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
                  )}
                >
                  <Icon className="size-4 shrink-0" />
                  {item.label}
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}
