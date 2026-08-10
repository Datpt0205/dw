"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, LogOut } from "lucide-react";
import { Badge, cn } from "@dw/ui";
import { useAuth } from "../lib/auth/auth-context";

const ROLE_BADGE: Record<
  string,
  { label: string; variant: "success" | "warning" | "secondary" }
> = {
  approver: { label: "chuyên gia mua sắm", variant: "success" },
  procurement_head: { label: "trưởng ban mua sắm", variant: "success" },
  platform_admin: { label: "quản trị", variant: "warning" },
  member: { label: "nhân viên", variant: "secondary" },
};

// Role hierarchy (low → high). Only the highest role a user holds is shown as a
// badge — a specialist isn't labelled "nhân viên · chuyên gia mua sắm", just the
// highest one, even though each tier includes every permission below it.
const ROLE_RANK = ["member", "approver", "procurement_head", "platform_admin"];

/**
 * Header chip: who is signed in + sign-out. The web is Chi's read-only back
 * office — An/Bình act through Slack, so there is no account switcher anymore.
 */
export function SessionChip() {
  const { status, displayName, roles, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open]);

  if (status !== "ready") return null;

  const topRole = roles
    .filter((r) => r in ROLE_BADGE)
    .sort((a, b) => ROLE_RANK.indexOf(b) - ROLE_RANK.indexOf(a))[0];
  const topBadge = topRole ? ROLE_BADGE[topRole] : undefined;
  const shown = topBadge ? [topBadge] : [];

  return (
    <div className="relative flex items-center gap-1.5" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-full border bg-card py-1 pl-1 pr-2.5 text-sm shadow-sm transition-colors hover:bg-accent/50"
      >
        <span className="flex size-6 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
          {(displayName || "?").charAt(0).toUpperCase()}
        </span>
        <span className="max-w-[9rem] truncate font-medium">
          {displayName || "Người dùng"}
        </span>
        {shown.map((b) => (
          <Badge key={b.label} variant={b.variant}>
            {b.label}
          </Badge>
        ))}
        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="absolute right-0 top-[calc(100%+8px)] z-50 w-64 overflow-hidden rounded-xl border bg-popover p-1.5 shadow-xl">
          <div className="px-2.5 py-2">
            <p className="truncate text-sm font-semibold">{displayName}</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {shown.map((b) => (
                <Badge key={b.label} variant={b.variant}>
                  {b.label}
                </Badge>
              ))}
            </div>
            <p className="mt-1.5 text-xs text-muted-foreground">
              Back office chỉ đọc — thao tác nghiệp vụ qua Slack.
            </p>
          </div>
          <div className="my-1 border-t" />
          <button
            type="button"
            onClick={logout}
            className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
          >
            <LogOut className="size-4" /> Đăng xuất
          </button>
        </div>
      )}
    </div>
  );
}
