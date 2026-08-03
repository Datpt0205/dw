"use client";

import { useState } from "react";
import { Bot, Loader2, LogIn, ShieldCheck } from "lucide-react";
import { Button } from "@dw/ui";
import { useAuth } from "../lib/auth/auth-context";
import { quickLogin } from "../lib/session";

/**
 * Full-screen gate shown when nobody is signed in.
 *
 * The web app is the read-only back office: An/Bình work entirely through the
 * Slack chat (their web logins are disabled in Keycloak). Only Chi (quản trị)
 * signs in here to observe — so the primary action is a one-click login.
 */
export function LoginScreen() {
  const { login, error } = useAuth();
  const [busy, setBusy] = useState(false);
  const [quickError, setQuickError] = useState<string | null>(null);

  async function loginAsChi() {
    setBusy(true);
    setQuickError(null);
    try {
      await quickLogin("chi", "demo");
      window.location.href = window.location.origin;
    } catch (reason) {
      setQuickError(
        reason instanceof Error ? reason.message : "Đăng nhập nhanh thất bại",
      );
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-md rounded-2xl border bg-card p-8 shadow-sm">
        <div className="mb-6 flex flex-col items-center gap-3 text-center">
          <span className="flex size-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Bot className="size-6" />
          </span>
          <div>
            <h1 className="text-xl font-semibold">Digital Worker Platform</h1>
            <p className="text-sm text-muted-foreground">
              Back office theo dõi &amp; kiểm toán — thao tác nghiệp vụ diễn ra
              trên Slack
            </p>
          </div>
        </div>

        {(error || quickError) && (
          <p className="mb-4 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {quickError ?? error}
          </p>
        )}

        <div className="flex flex-col gap-3">
          <Button size="lg" onClick={() => void loginAsChi()} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <ShieldCheck />}
            Vào với vai Chi — Quản trị
          </Button>
          <Button size="lg" variant="outline" onClick={login} disabled={busy}>
            <LogIn /> Đăng nhập SSO khác
          </Button>
        </div>

        <div className="mt-6 rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">
          <p className="font-medium text-foreground">Tài khoản back office</p>
          <p className="mt-1">
            <code>chi</code> — mật khẩu <code>demo</code>. An &amp; Bình làm
            việc qua chat với Ngọc trên Slack, không đăng nhập web.
          </p>
        </div>
      </div>
    </div>
  );
}
