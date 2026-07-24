"use client";

import { Check, ShieldCheck } from "lucide-react";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@dw/ui";
import { useAuth } from "../../lib/auth/auth-context";

/**
 * Access reference page. Identity is managed by Keycloak; business permissions
 * (roles → scopes) live in the platform database. New accounts join the demo
 * workspace as `member`; an admin adjusts roles from here in a later milestone.
 */

const ROLE_CATALOG: {
  key: string;
  label: string;
  summary: string;
  scopes: string[];
}[] = [
  {
    key: "member",
    label: "Nhân viên (member)",
    summary: "Tạo & chạy phân tích đấu thầu, cuộc họp. Không được phê duyệt.",
    scopes: [
      "tender.read",
      "tender.write",
      "work_ops.read",
      "work_ops.write",
      "approvals.read",
      "knowledge.read",
      "memory.read",
    ],
  },
  {
    key: "approver",
    label: "Người phê duyệt (approver)",
    summary: "Xem và quyết định phê duyệt. Không tạo nội dung.",
    scopes: [
      "approvals.read",
      "approvals.decide",
      "tender.read",
      "work_ops.read",
      "knowledge.read",
      "memory.read",
    ],
  },
  {
    key: "platform_admin",
    label: "Quản trị (platform_admin)",
    summary: "Toàn quyền trong workspace — bỏ qua mọi kiểm tra scope.",
    scopes: ["platform.admin", "(bypass mọi scope)"],
  },
];

export default function AdminPage() {
  const { displayName, active, roles, scopes } = useAuth();

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Phân quyền &amp; vai trò
        </h1>
        <p className="text-sm text-muted-foreground">
          Keycloak quản lý đăng nhập; Digital Worker quản lý quyền nghiệp vụ theo
          vai trò trong từng workspace.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="size-4 text-success" /> Quyền của bạn
          </CardTitle>
          <CardDescription>
            {displayName}
            {active ? ` · ${active.workspaceName} (${active.tenantName})` : ""}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-muted-foreground">Vai trò:</span>
            {roles.length > 0 ? (
              roles.map((r) => (
                <Badge key={r} variant="secondary">
                  {r}
                </Badge>
              ))
            ) : (
              <span className="text-muted-foreground">—</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-muted-foreground">Scope hiệu lực:</span>
            {scopes.length > 0 ? (
              scopes.map((s) => (
                <code
                  key={s}
                  className="rounded bg-muted px-1.5 py-0.5 text-xs"
                >
                  {s}
                </code>
              ))
            ) : (
              <span className="text-muted-foreground">
                (platform_admin — bỏ qua kiểm tra scope)
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        {ROLE_CATALOG.map((role) => {
          const mine = roles.includes(role.key);
          return (
            <Card key={role.key} className={mine ? "border-primary" : ""}>
              <CardHeader>
                <CardTitle className="flex items-center justify-between text-sm">
                  {role.label}
                  {mine && <Check className="size-4 text-primary" />}
                </CardTitle>
                <CardDescription>{role.summary}</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1">
                {role.scopes.map((s) => (
                  <code
                    key={s}
                    className="rounded bg-muted px-1.5 py-0.5 text-[11px]"
                  >
                    {s}
                  </code>
                ))}
              </CardContent>
            </Card>
          );
        })}
      </div>

      <p className="text-xs text-muted-foreground">
        Tài khoản mới đăng ký qua Keycloak sẽ tự động được thêm vào workspace demo
        với vai <strong>Nhân viên</strong>. Việc nâng/hạ vai trò sẽ do quản trị
        viên thao tác (bổ sung ở giai đoạn sau).
      </p>
    </div>
  );
}
