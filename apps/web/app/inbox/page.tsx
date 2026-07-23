"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { Approval } from "@dw/contracts";
import { Card, CardContent, CardHeader, CardTitle } from "@dw/ui";
import { apiClient } from "../../lib/session";

export default function InboxPage() {
  const [approvals, setApprovals] = useState<Approval[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient()
      .listApprovals()
      .then(setApprovals)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "lỗi không rõ"),
      );
  }, []);

  const pending = approvals?.filter((a) => a.status === "pending") ?? [];
  const decided = approvals?.filter((a) => a.status !== "pending") ?? [];

  return (
    <div className="max-w-4xl space-y-6">
      <h1 className="text-2xl font-bold">Inbox</h1>
      <p className="text-sm text-slate-500">
        Việc đang chờ bạn xử lý trong workspace này.
      </p>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {approvals === null && !error && <p className="text-sm">Đang tải…</p>}

      <Card>
        <CardHeader>
          <CardTitle>⏳ Chờ phê duyệt ({pending.length})</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {pending.length === 0 && (
            <p className="text-sm text-slate-500">
              Không có yêu cầu phê duyệt nào đang chờ.
            </p>
          )}
          {pending.map((approval) => (
            <Link
              key={approval.id}
              href="/approvals"
              className="block rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm hover:border-amber-400 dark:border-amber-900 dark:bg-amber-950"
            >
              <span className="font-medium">{approval.approval_type}</span>
              <p className="text-xs text-slate-600 dark:text-slate-300">
                {approval.reason}
              </p>
            </Link>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Đã quyết định gần đây ({decided.length})</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {decided.slice(0, 10).map((approval) => (
            <div
              key={approval.id}
              className="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-800"
            >
              <span className="font-medium">{approval.approval_type}</span>{" "}
              <span
                className={
                  approval.status === "approved"
                    ? "text-green-700 dark:text-green-400"
                    : "text-red-600"
                }
              >
                {approval.status}
              </span>
              <p className="text-xs text-slate-500">{approval.reason}</p>
            </div>
          ))}
          {decided.length === 0 && (
            <p className="text-sm text-slate-500">Chưa có quyết định nào.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
