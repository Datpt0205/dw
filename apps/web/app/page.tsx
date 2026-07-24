"use client";

import Link from "next/link";
import { ArrowRight, BadgeCheck, FileSearch, ShieldCheck } from "lucide-react";
import { Badge, Card, CardContent } from "@dw/ui";
import { useAuth } from "../lib/auth/auth-context";

const ROLE_LABELS: Record<string, string> = {
  member: "Nhân viên",
  approver: "Người phê duyệt",
  platform_admin: "Quản trị",
};

interface ModuleCard {
  href: string;
  title: string;
  description: string;
  icon: typeof FileSearch;
  color: string;
  scope: string;
}

const MODULES: ModuleCard[] = [
  {
    href: "/procurement/dw01",
    title: "Xây hồ sơ thầu (DW01)",
    description:
      "PR đã duyệt → chuẩn hoá nhu cầu, chọn phương án (CP1), soạn RFQ/tiêu chí/shortlist (CP2), khoá bản chính thức.",
    icon: FileSearch,
    color: "bg-blue-50 text-blue-600",
    scope: "tender.read",
  },
  {
    href: "/approvals",
    title: "Phê duyệt",
    description:
      "Worker luôn dừng tại đây trước khi thực hiện hành động thật. Chỉ vai phê duyệt mới quyết định.",
    icon: BadgeCheck,
    color: "bg-amber-50 text-amber-600",
    scope: "approvals.decide",
  },
];

export default function HomePage() {
  const { displayName, active, roles, hasScope } = useAuth();
  const modules = MODULES.filter((m) => hasScope(m.scope));

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Xin chào, {displayName}
        </h1>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <ShieldCheck className="size-4 text-success" />
          {active ? `${active.workspaceName} · ${active.tenantName}` : ""}
          {roles.map((role) => (
            <Badge key={role} variant="secondary">
              {ROLE_LABELS[role] ?? role}
            </Badge>
          ))}
        </p>
      </div>

      <p className="max-w-xl text-sm text-muted-foreground">
        Máy phân tích và đề xuất — con người luôn phê duyệt trước khi bất kỳ hành
        động thật nào xảy ra. Bạn chỉ thấy các chức năng phù hợp với quyền của
        mình.
      </p>

      <div className="grid gap-5 md:grid-cols-2">
        {modules.map((m) => {
          const Icon = m.icon;
          return (
            <Link key={m.href} href={m.href} className="group">
              <Card className="h-full transition-all group-hover:-translate-y-0.5 group-hover:shadow-md">
                <CardContent className="pt-6">
                  <span
                    className={`flex size-11 items-center justify-center rounded-xl ${m.color}`}
                  >
                    <Icon className="size-6" />
                  </span>
                  <h2 className="mt-4 flex items-center gap-2 text-lg font-semibold">
                    {m.title}
                    <ArrowRight className="size-4 opacity-0 transition-opacity group-hover:opacity-100" />
                  </h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {m.description}
                  </p>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>

      <p className="text-xs text-muted-foreground">
        Trang hệ thống:{" "}
        <Link className="underline hover:text-foreground" href="/audit">
          Nhật ký
        </Link>
        {hasScope("knowledge.read") && (
          <>
            {" · "}
            <Link className="underline hover:text-foreground" href="/knowledge">
              Tri thức
            </Link>
          </>
        )}
        {hasScope("memory.read") && (
          <>
            {" · "}
            <Link className="underline hover:text-foreground" href="/memory">
              Trí nhớ
            </Link>
          </>
        )}
        {" · "}
        <Link className="underline hover:text-foreground" href="/integrations">
          Tích hợp
        </Link>
      </p>
    </div>
  );
}
