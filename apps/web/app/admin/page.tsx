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
import { PageHeading } from "../../components/page-heading";
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
    label: "Nhân viên nghiệp vụ",
    summary:
      "Tạo và theo dõi hồ sơ đấu thầu. Không được ra quyết định phê duyệt.",
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
    label: "Người phê duyệt",
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
    label: "Quản trị hệ thống",
    summary: "Quản lý thành viên, vai trò và toàn bộ chức năng trong đơn vị.",
    scopes: ["platform.admin", "(bypass mọi scope)"],
  },
];

const SCOPE_LABELS: Record<string, string> = {
  "tender.read": "Xem hồ sơ thầu",
  "tender.write": "Tạo và cập nhật hồ sơ thầu",
  "work_ops.read": "Xem công việc",
  "work_ops.write": "Cập nhật công việc",
  "approvals.read": "Xem yêu cầu phê duyệt",
  "approvals.decide": "Ra quyết định phê duyệt",
  "knowledge.read": "Xem kho tài liệu",
  "memory.read": "Xem lịch sử xử lý",
  "platform.admin": "Quản trị toàn hệ thống",
  "(bypass mọi scope)": "Toàn quyền",
};

function scopeLabel(scope: string) {
  return SCOPE_LABELS[scope] ?? scope;
}

function roleLabel(role: string) {
  return ROLE_CATALOG.find((item) => item.key === role)?.label ?? role;
}

export default function AdminPage() {
  const { displayName, active, roles, scopes } = useAuth();

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeading
        eyebrow="Quản trị đơn vị"
        icon={ShieldCheck}
        title="Phân quyền và vai trò"
        description="Quyền sử dụng được cấp theo vai trò của từng thành viên trong đơn vị làm việc."
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="size-4 text-success" /> Quyền của bạn
          </CardTitle>
          <CardDescription>
            {displayName}
            {active ? ` · ${active.workspaceName}` : ""}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-muted-foreground">Vai trò:</span>
            {roles.length > 0 ? (
              roles.map((r) => (
                <Badge key={r} variant="secondary">
                  {roleLabel(r)}
                </Badge>
              ))
            ) : (
              <span className="text-muted-foreground">—</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-muted-foreground">Quyền được cấp:</span>
            {scopes.length > 0 ? (
              scopes.map((s) => (
                <span key={s} className="rounded bg-muted px-2 py-1 text-xs">
                  {scopeLabel(s)}
                </span>
              ))
            ) : (
              <span className="text-muted-foreground">Toàn quyền quản trị</span>
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
                <CardTitle className="flex items-start justify-between gap-3 text-sm">
                  {role.label}
                  {mine && <Check className="size-4 text-primary" />}
                </CardTitle>
                <CardDescription>{role.summary}</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1">
                {role.scopes.map((s) => (
                  <span
                    key={s}
                    className="rounded bg-muted px-2 py-1 text-[11px]"
                  >
                    {scopeLabel(s)}
                  </span>
                ))}
              </CardContent>
            </Card>
          );
        })}
      </div>

      <p className="text-xs text-muted-foreground">
        Tài khoản mới đăng ký sẽ tự động được thêm vào đơn vị demo với vai{" "}
        <strong>Nhân viên nghiệp vụ</strong>. Quản trị viên chịu trách nhiệm
        thay đổi vai trò khi cần.
      </p>
    </div>
  );
}
