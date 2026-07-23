"use client";

import { useEffect, useState } from "react";
import { LogIn, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import type { DemoUser } from "@dw/contracts";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Textarea,
} from "@dw/ui";
import {
  apiClient,
  clearSession,
  loadSession,
  loginAs,
  saveSession,
  type DevSession,
} from "../../lib/session";

const ROLE_BADGES: Record<
  string,
  { label: string; variant: "secondary" | "success" | "warning" }
> = {
  member: { label: "Nhân viên", variant: "secondary" },
  approver: { label: "Người phê duyệt", variant: "success" },
  platform_admin: { label: "Quản trị", variant: "warning" },
};

export default function AdminPage() {
  const [users, setUsers] = useState<DemoUser[] | null>(null);
  const [session, setSession] = useState<DevSession | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showManual, setShowManual] = useState(false);
  const [token, setToken] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");

  useEffect(() => {
    setSession(loadSession());
    apiClient()
      .listDemoUsers()
      .then(setUsers)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "lỗi không rõ"),
      );
  }, []);

  async function handleLogin(user: DemoUser) {
    setBusy(user.subject);
    setError(null);
    try {
      setSession(await loginAs(user.subject));
      toast.success(`Đã đăng nhập với vai ${user.display_name}`);
    } catch (e) {
      const message = e instanceof Error ? e.message : "lỗi không rõ";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Đăng nhập demo
        </h1>
        <p className="text-sm text-muted-foreground">
          Chọn một nhân vật. Backend vẫn xác minh token + membership trong DB
          trên mọi request — nút này chỉ có ở môi trường dev.
        </p>
      </div>

      {session && (
        <Card className="border-success/40">
          <CardContent className="flex items-center justify-between pt-5 text-sm">
            <span className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-success" />
              Đang đăng nhập:{" "}
              <strong>
                {session.displayName ?? session.subject ?? "thủ công"}
              </strong>
              {session.tenantName && (
                <span className="text-muted-foreground">
                  · {session.tenantName}
                </span>
              )}
              {session.roles?.map((role) => {
                const badge = ROLE_BADGES[role];
                return (
                  <Badge key={role} variant={badge?.variant ?? "secondary"}>
                    {badge?.label ?? role}
                  </Badge>
                );
              })}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                clearSession();
                setSession(null);
              }}
            >
              Đăng xuất
            </Button>
          </CardContent>
        </Card>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="grid gap-3 sm:grid-cols-2">
        {users?.map((user) => (
          <Card key={user.subject} className="flex flex-col">
            <CardHeader className="flex-row items-center gap-3 space-y-0">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                {user.display_name.split(" ").at(-1)?.charAt(0)}
              </span>
              <div>
                <CardTitle className="text-base">{user.display_name}</CardTitle>
                <CardDescription>{user.tenant_name}</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="flex flex-1 flex-col justify-between gap-3 text-sm">
              <p className="text-muted-foreground">{user.description}</p>
              <div className="flex items-center justify-between gap-2">
                <span className="flex flex-wrap gap-1">
                  {user.roles.map((role) => {
                    const badge = ROLE_BADGES[role];
                    return (
                      <Badge key={role} variant={badge?.variant ?? "secondary"}>
                        {badge?.label ?? role}
                      </Badge>
                    );
                  })}
                </span>
                <Button
                  size="sm"
                  onClick={() => void handleLogin(user)}
                  disabled={busy !== null}
                >
                  <LogIn />
                  {busy === user.subject ? "Đang vào…" : "Đăng nhập"}
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <button
        className="text-xs text-muted-foreground underline"
        onClick={() => setShowManual((v) => !v)}
      >
        {showManual ? "Ẩn" : "Nâng cao: dán token thủ công"}
      </button>
      {showManual && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Phiên thủ công</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <label className="block text-sm">
              Bearer token
              <Textarea
                className="mt-1 font-mono text-xs"
                rows={3}
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </label>
            <label className="block text-sm">
              Tenant ID
              <Input
                className="mt-1 font-mono text-xs"
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
              />
            </label>
            <label className="block text-sm">
              Workspace ID
              <Input
                className="mt-1 font-mono text-xs"
                value={workspaceId}
                onChange={(e) => setWorkspaceId(e.target.value)}
              />
            </label>
            <Button
              onClick={() => {
                saveSession({ token, tenantId, workspaceId });
                setSession(loadSession());
              }}
            >
              Lưu phiên
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
