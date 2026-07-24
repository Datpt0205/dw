"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bot, Loader2, LogOut } from "lucide-react";
import { Button } from "@dw/ui";
import { useAuth } from "../lib/auth/auth-context";
import { LoginScreen } from "./login-screen";
import { NavLinks } from "./nav-links";
import { SessionChip } from "./session-chip";
import { WorkspaceSelector } from "./workspace-selector";

function CenteredCard({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-md rounded-2xl border bg-card p-8 text-center shadow-sm">
        {children}
      </div>
    </div>
  );
}

/** Auth gate + application shell. Children render only once a workspace is
 * active; every other state gets a dedicated full-screen view. */
export function AppFrame({ children }: { children: ReactNode }) {
  const { status, error, hasScope, logout } = useAuth();
  const pathname = usePathname();

  // The dev-login page renders outside the gate (it is how you authenticate).
  if (pathname === "/dev-login") return <>{children}</>;

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 size-5 animate-spin" /> Đang tải…
      </div>
    );
  }

  if (status === "unauthenticated") return <LoginScreen />;

  if (status === "error") {
    return (
      <CenteredCard>
        <h1 className="text-lg font-semibold">Không kết nối được máy chủ</h1>
        <p className="mt-2 text-sm text-muted-foreground">{error}</p>
        <div className="mt-5 flex justify-center gap-2">
          <Button onClick={() => window.location.reload()}>Thử lại</Button>
          <Button variant="outline" onClick={logout}>
            Đăng xuất
          </Button>
        </div>
      </CenteredCard>
    );
  }

  if (status === "no-workspace") {
    return (
      <CenteredCard>
        <h1 className="text-lg font-semibold">Chưa có không gian làm việc</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Tài khoản của bạn đã đăng nhập nhưng chưa được gán vào workspace nào.
          Liên hệ quản trị viên để được cấp quyền.
        </p>
        <Button className="mt-5" variant="outline" onClick={logout}>
          <LogOut /> Đăng xuất
        </Button>
      </CenteredCard>
    );
  }

  // status === "ready"
  return (
    <>
      <div className="flex min-h-screen">
        <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r bg-sidebar px-3 py-4 md:flex">
          <Link
            href="/"
            className="mb-6 flex items-center gap-2 px-2 text-base font-semibold"
          >
            <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Bot className="size-5" />
            </span>
            Digital Worker
          </Link>
          <div className="flex-1">
            <NavLinks />
          </div>
          <p className="px-2 text-[10px] leading-relaxed text-muted-foreground/70">
            Hệ thống:{" "}
            <Link className="underline" href="/audit">
              Nhật ký
            </Link>
            {hasScope("workspace.members.read") && (
              <>
                {" · "}
                <Link className="underline" href="/admin">
                  Quản trị
                </Link>
              </>
            )}
          </p>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-10 flex h-14 items-center justify-between gap-3 border-b bg-background/80 px-6 backdrop-blur">
            <WorkspaceSelector />
            <SessionChip />
          </header>
          <main className="flex-1 p-6 md:p-8">{children}</main>
        </div>
      </div>
    </>
  );
}
