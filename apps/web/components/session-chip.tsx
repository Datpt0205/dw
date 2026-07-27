"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Loader2, LogOut, Repeat } from "lucide-react";
import { Badge, cn } from "@dw/ui";
import { useAuth } from "../lib/auth/auth-context";
import { quickLogin } from "../lib/session";

const ROLE_BADGE: Record<
  string,
  { label: string; variant: "success" | "warning" | "secondary" }
> = {
  approver: { label: "phê duyệt", variant: "success" },
  platform_admin: { label: "quản trị", variant: "warning" },
  member: { label: "nhân viên", variant: "secondary" },
};

// Demo personas for the fast account switcher (public demo credentials).
const QUICK_PERSONAS = [
  { username: "an.nguyen", name: "Nguyễn Văn An", role: "nhân viên" },
  { username: "binh.tran", name: "Trần Thị Bình", role: "phê duyệt" },
  { username: "chi.le", name: "Lê Thị Chi", role: "quản trị" },
];
const DEMO_PASSWORD = "demo-password";

/** Header chip: who is signed in + one-click account switch + sign-out. */
export function SessionChip() {
  const { status, mode, displayName, roles, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
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

  const shown = roles
    .map((r) => ROLE_BADGE[r])
    .filter((b): b is { label: string; variant: "success" | "warning" | "secondary" } => b !== undefined)
    .slice(0, 2);

  const canQuickSwitch = mode === "oidc";
  const currentName = (displayName || "").toLowerCase();

  async function switchTo(username: string) {
    setSwitching(username);
    setError(null);
    try {
      await quickLogin(username, DEMO_PASSWORD);
      window.location.href = window.location.origin;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Đổi tài khoản lỗi");
      setSwitching(null);
    }
  }

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
        <div className="absolute right-0 top-[calc(100%+8px)] z-50 w-72 overflow-hidden rounded-xl border bg-popover p-1.5 shadow-xl">
          <div className="px-2.5 py-2">
            <p className="truncate text-sm font-semibold">{displayName}</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {shown.map((b) => (
                <Badge key={b.label} variant={b.variant}>
                  {b.label}
                </Badge>
              ))}
            </div>
          </div>

          {canQuickSwitch && (
            <>
              <div className="my-1 border-t" />
              <p className="flex items-center gap-1.5 px-2.5 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                <Repeat className="size-3" /> Đổi nhanh tài khoản
              </p>
              {QUICK_PERSONAS.map((persona) => {
                const isCurrent = currentName === persona.name.toLowerCase();
                return (
                  <button
                    key={persona.username}
                    type="button"
                    disabled={isCurrent || switching !== null}
                    onClick={() => void switchTo(persona.username)}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition-colors",
                      isCurrent
                        ? "cursor-default text-muted-foreground"
                        : "hover:bg-accent",
                      switching !== null && !isCurrent && "opacity-60",
                    )}
                  >
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold">
                      {persona.name.charAt(0)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">
                        {persona.name}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {persona.role}
                      </span>
                    </span>
                    {switching === persona.username ? (
                      <Loader2 className="size-4 animate-spin text-muted-foreground" />
                    ) : isCurrent ? (
                      <Check className="size-4 text-success" />
                    ) : null}
                  </button>
                );
              })}
              {error && (
                <p className="px-2.5 py-1 text-xs text-destructive">{error}</p>
              )}
            </>
          )}

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
