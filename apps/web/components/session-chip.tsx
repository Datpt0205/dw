"use client";

import { LogOut } from "lucide-react";
import { Badge, Button } from "@dw/ui";
import { useAuth } from "../lib/auth/auth-context";

const ROLE_BADGE: Record<string, { label: string; variant: "success" | "warning" | "secondary" }> = {
  approver: { label: "phê duyệt", variant: "success" },
  platform_admin: { label: "admin", variant: "warning" },
  member: { label: "nhân viên", variant: "secondary" },
};

/** Header chip: who is signed in, with one-click sign-out. */
export function SessionChip() {
  const { status, displayName, roles, logout } = useAuth();

  if (status !== "ready") return null;

  const shown = roles
    .map((r) => ROLE_BADGE[r])
    .filter((b): b is { label: string; variant: "success" | "warning" | "secondary" } =>
      b !== undefined,
    )
    .slice(0, 2);

  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-2 rounded-full border bg-card py-1 pl-1 pr-3 text-sm shadow-sm">
        <span className="flex size-6 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
          {(displayName || "?").charAt(0).toUpperCase()}
        </span>
        <span className="font-medium">{displayName || "Người dùng"}</span>
        {shown.map((b) => (
          <Badge key={b.label} variant={b.variant}>
            {b.label}
          </Badge>
        ))}
      </div>
      <Button variant="ghost" size="icon" title="Đăng xuất" onClick={logout}>
        <LogOut />
      </Button>
    </div>
  );
}
