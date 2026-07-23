"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface NavItem {
  href: string;
  label: string;
  hint: string;
}

const GROUPS: Array<{ title: string; items: NavItem[] }> = [
  {
    title: "Làm việc",
    items: [
      { href: "/home", label: "Home", hint: "Luồng demo từng bước" },
      { href: "/inbox", label: "Inbox", hint: "Việc đang chờ bạn" },
      {
        href: "/approvals",
        label: "Approvals",
        hint: "Duyệt / từ chối đề xuất",
      },
    ],
  },
  {
    title: "Nghiệp vụ",
    items: [
      {
        href: "/procurement",
        label: "Procurement",
        hint: "Phân tích hồ sơ thầu",
      },
      { href: "/work-ops", label: "Work Ops", hint: "Họp → action item" },
    ],
  },
  {
    title: "Nền tảng",
    items: [
      { href: "/knowledge", label: "Knowledge", hint: "Tài liệu đã ingest" },
      { href: "/memory", label: "Memory", hint: "Trí nhớ dài hạn của máy" },
      { href: "/integrations", label: "Integrations", hint: "Tool + policy" },
      { href: "/audit", label: "Audit", hint: "Nhật ký bất biến" },
    ],
  },
  {
    title: "Hệ thống",
    items: [{ href: "/admin", label: "Admin", hint: "Đăng nhập demo" }],
  },
];

export function NavLinks() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main navigation" className="space-y-4">
      {GROUPS.map((group) => (
        <div key={group.title}>
          <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
            {group.title}
          </p>
          <div className="space-y-0.5">
            {group.items.map((item) => {
              const active =
                pathname === item.href || pathname.startsWith(item.href + "/");
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  title={item.hint}
                  className={
                    active
                      ? "block rounded-md bg-slate-100 px-3 py-1.5 text-sm font-semibold text-slate-900 dark:bg-slate-800 dark:text-white"
                      : "block rounded-md px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
                  }
                >
                  {item.label}
                  <span className="block text-[10px] font-normal leading-tight text-slate-400 dark:text-slate-500">
                    {item.hint}
                  </span>
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}
