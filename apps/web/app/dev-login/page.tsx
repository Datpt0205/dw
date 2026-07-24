"use client";

import { useEffect, useState } from "react";
import { Bot, LogIn } from "lucide-react";
import type { DemoUser } from "@dw/contracts";
import { Badge, Button, Card, CardContent } from "@dw/ui";
import { AUTH_MODE } from "../../lib/auth/config";
import { apiClient, loginAsDev } from "../../lib/session";

const ROLE_LABEL: Record<string, string> = {
  member: "Nhân viên",
  approver: "Người phê duyệt",
  platform_admin: "Quản trị",
};

/** Dev-only one-click login (host `make dev` without Keycloak). */
export default function DevLoginPage() {
  const [users, setUsers] = useState<DemoUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    apiClient()
      .listDemoUsers()
      .then(setUsers)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "không tải được"),
      );
  }, []);

  async function pick(subject: string) {
    setBusy(subject);
    try {
      await loginAsDev(subject);
      window.location.href = "/";
    } catch (e) {
      setError(e instanceof Error ? e.message : "đăng nhập lỗi");
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 p-6">
      <div className="flex items-center gap-3">
        <span className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <Bot className="size-5" />
        </span>
        <div>
          <h1 className="text-xl font-semibold">Đăng nhập (chế độ dev)</h1>
          <p className="text-sm text-muted-foreground">
            Chọn một tài khoản demo để vào nhanh.
          </p>
        </div>
      </div>

      {AUTH_MODE !== "dev" && (
        <p className="rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
          Ứng dụng đang ở chế độ OIDC — trang này chỉ dùng khi
          <code> NEXT_PUBLIC_AUTH_MODE=dev</code>.
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="grid gap-3 sm:grid-cols-2">
        {users?.map((u) => (
          <Card key={u.subject}>
            <CardContent className="flex flex-col gap-3 pt-5">
              <div>
                <p className="font-medium">{u.display_name}</p>
                <p className="text-xs text-muted-foreground">{u.tenant_name}</p>
              </div>
              <div className="flex flex-wrap gap-1">
                {u.roles.map((r) => (
                  <Badge key={r} variant="secondary">
                    {ROLE_LABEL[r] ?? r}
                  </Badge>
                ))}
              </div>
              <Button
                size="sm"
                disabled={busy === u.subject}
                onClick={() => void pick(u.subject)}
              >
                <LogIn /> {busy === u.subject ? "Đang vào…" : "Đăng nhập"}
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
