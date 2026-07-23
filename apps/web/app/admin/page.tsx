"use client";

import { useEffect, useState } from "react";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@dw/ui";
import { clearSession, loadSession, saveSession } from "../../lib/session";

export default function AdminPage() {
  const [token, setToken] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const session = loadSession();
    if (session) {
      setToken(session.token);
      setTenantId(session.tenantId);
      setWorkspaceId(session.workspaceId);
    }
  }, []);

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold">Admin — Dev session</h1>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Dán dev token (tạo bằng <code>scripts/issue_dev_token.py</code>) cùng
        tenant/workspace UUID từ seed. Backend luôn xác minh lại — đây chỉ là
        tiện ích phát triển.
      </p>
      <Card>
        <CardHeader>
          <CardTitle>Phiên làm việc</CardTitle>
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
          <div className="flex gap-2">
            <Button
              onClick={() => {
                saveSession({ token, tenantId, workspaceId });
                setSaved(true);
                setTimeout(() => setSaved(false), 2000);
              }}
            >
              Lưu phiên
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                clearSession();
                setToken("");
                setTenantId("");
                setWorkspaceId("");
              }}
            >
              Xoá phiên
            </Button>
            {saved && (
              <span className="self-center text-sm text-green-600">
                Đã lưu ✓
              </span>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
