"use client";

import { useEffect, useState } from "react";
import type { DemoUser } from "@dw/contracts";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@dw/ui";
import {
  apiClient,
  clearSession,
  loadSession,
  loginAs,
  saveSession,
  type DevSession,
} from "../../lib/session";

const ROLE_LABELS: Record<string, string> = {
  member: "Nhân viên",
  approver: "Người phê duyệt",
  platform_admin: "Quản trị",
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

  async function handleLogin(subject: string) {
    setBusy(subject);
    setError(null);
    try {
      setSession(await loginAs(subject));
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Đăng nhập demo</h1>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Chọn một nhân vật để trải nghiệm nền tảng. Backend luôn xác minh token
          + membership trong DB trên mọi request — nút này chỉ thay cho việc dán
          token thủ công (chỉ có ở môi trường dev).
        </p>
      </div>

      {session && (
        <Card>
          <CardContent className="flex items-center justify-between pt-4">
            <div className="text-sm">
              Đang đăng nhập:{" "}
              <strong>
                {session.displayName ?? session.subject ?? "thủ công"}
              </strong>
              {session.tenantName && (
                <span className="text-slate-500"> · {session.tenantName}</span>
              )}
              {session.roles && (
                <span className="ml-2 space-x-1">
                  {session.roles.map((role) => (
                    <span
                      key={role}
                      className="rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                    >
                      {ROLE_LABELS[role] ?? role}
                    </span>
                  ))}
                </span>
              )}
            </div>
            <Button
              variant="outline"
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

      {error && <p className="text-sm text-red-600">{error}</p>}
      {users === null && !error && (
        <p className="text-sm">Đang tải danh sách…</p>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        {users?.map((user) => (
          <Card key={user.subject}>
            <CardHeader>
              <CardTitle className="flex items-center justify-between text-base">
                {user.display_name}
                <span className="text-xs font-normal text-slate-500">
                  {user.tenant_name}
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p className="text-slate-600 dark:text-slate-400">
                {user.description}
              </p>
              <div className="flex items-center justify-between">
                <span className="space-x-1">
                  {user.roles.map((role) => (
                    <span
                      key={role}
                      className="rounded bg-slate-100 px-2 py-0.5 text-xs dark:bg-slate-800"
                    >
                      {ROLE_LABELS[role] ?? role}
                    </span>
                  ))}
                </span>
                <Button
                  onClick={() => void handleLogin(user.subject)}
                  disabled={busy !== null}
                >
                  {busy === user.subject ? "Đang vào…" : "Đăng nhập"}
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <button
        className="text-xs text-slate-500 underline"
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
              <textarea
                className="mt-1 w-full rounded-md border border-slate-300 p-2 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
                rows={3}
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </label>
            <label className="block text-sm">
              Tenant ID
              <input
                className="mt-1 w-full rounded-md border border-slate-300 p-2 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
              />
            </label>
            <label className="block text-sm">
              Workspace ID
              <input
                className="mt-1 w-full rounded-md border border-slate-300 p-2 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
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
