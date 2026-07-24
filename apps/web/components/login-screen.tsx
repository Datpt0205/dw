"use client";

import { Bot, LogIn, UserPlus } from "lucide-react";
import { Button } from "@dw/ui";
import { useAuth } from "../lib/auth/auth-context";

/** Full-screen gate shown when nobody is signed in. */
export function LoginScreen() {
  const { login, register, error } = useAuth();
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
              Đăng nhập để vào không gian làm việc của bạn
            </p>
          </div>
        </div>

        {error && (
          <p className="mb-4 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        )}

        <div className="flex flex-col gap-3">
          <Button size="lg" onClick={login}>
            <LogIn /> Đăng nhập
          </Button>
          <Button size="lg" variant="outline" onClick={register}>
            <UserPlus /> Đăng ký tài khoản mới
          </Button>
        </div>

        <div className="mt-6 rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">
          <p className="font-medium text-foreground">Tài khoản demo</p>
          <p className="mt-1">
            <code>an.nguyen</code> · <code>binh.tran</code> · <code>chi.le</code>{" "}
            — mật khẩu <code>demo-password</code>
          </p>
          <p className="mt-1">
            Tài khoản mới đăng ký sẽ tự vào workspace demo với vai{" "}
            <strong>Nhân viên</strong>.
          </p>
        </div>
      </div>
    </div>
  );
}
