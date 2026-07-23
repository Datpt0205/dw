"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { LogOut, UserRound } from "lucide-react";
import { Badge, Button } from "@dw/ui";
import { clearSession, loadSession, type DevSession } from "../lib/session";

/** Header chip: who is signed in, with one-click sign-out. */
export function SessionChip() {
  const [session, setSession] = useState<DevSession | null>(null);

  useEffect(() => {
    setSession(loadSession());
    const sync = () => setSession(loadSession());
    window.addEventListener("storage", sync);
    window.addEventListener("focus", sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener("focus", sync);
    };
  }, []);

  if (!session) {
    return (
      <Button asChild size="sm">
        <Link href="/admin">
          <UserRound /> Đăng nhập demo
        </Link>
      </Button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-2 rounded-full border bg-card py-1 pl-1 pr-3 text-sm shadow-sm">
        <span className="flex size-6 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
          {(session.displayName ?? "?").charAt(0)}
        </span>
        <span className="font-medium">
          {session.displayName ?? "Phiên thủ công"}
        </span>
        {session.roles?.includes("approver") && (
          <Badge variant="success">phê duyệt</Badge>
        )}
        {session.roles?.includes("platform_admin") && (
          <Badge variant="warning">admin</Badge>
        )}
      </div>
      <Button
        variant="ghost"
        size="icon"
        title="Đăng xuất"
        onClick={() => {
          clearSession();
          window.location.reload();
        }}
      >
        <LogOut />
      </Button>
    </div>
  );
}
