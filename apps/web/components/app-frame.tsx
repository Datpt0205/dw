"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bot, Loader2, LogOut, ScrollText, Settings } from "lucide-react";
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
          Tài khoản của bạn đã đăng nhập nhưng chưa được gán vào đơn vị làm việc
          nào. Liên hệ quản trị viên để được cấp quyền.
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
      <div className="flex min-h-screen bg-background">
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-[#d5e0e9] bg-sidebar px-4 py-5 md:flex">
          <Link href="/" className="mb-7 flex items-center gap-3 px-2">
            <span className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <Bot className="size-5" />
            </span>
            <span>
              <span className="block text-sm font-bold tracking-tight">
                Procurement AI
              </span>
              <span className="block text-[10px] font-medium uppercase tracking-[0.13em] text-muted-foreground">
                Digital Worker
              </span>
            </span>
          </Link>
          <div className="flex-1">
            <NavLinks />
          </div>
          <div className="space-y-1 border-t pt-4 text-xs text-muted-foreground">
            <Link
              className="flex items-center gap-2 rounded-lg px-3 py-2 hover:bg-sidebar-accent hover:text-foreground"
              href="/audit"
            >
              <ScrollText className="size-3.5" /> Nhật ký hệ thống
            </Link>
            {hasScope("workspace.members.read") && (
              <Link
                className="flex items-center gap-2 rounded-lg px-3 py-2 hover:bg-sidebar-accent hover:text-foreground"
                href="/admin"
              >
                <Settings className="size-3.5" /> Phân quyền
              </Link>
            )}
          </div>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 border-b border-[#d5e0e9] bg-white/95 backdrop-blur-xl">
            <div className="flex h-16 items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
              <div className="flex min-w-0 items-center gap-3">
                <Link
                  href="/"
                  className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground md:hidden"
                >
                  <Bot className="size-5" />
                </Link>
                <WorkspaceSelector />
              </div>
              <SessionChip />
            </div>
            <div className="overflow-x-auto border-t px-3 py-2 md:hidden">
              <NavLinks mobile />
            </div>
          </header>
          <main className="flex-1 px-4 py-7 sm:px-6 lg:px-10 lg:py-9">
            {children}
          </main>
        </div>
      </div>
    </>
  );
}
