"use client";

import { useCallback, useEffect, useState } from "react";
import type { Approval } from "@dw/contracts";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@dw/ui";
import { apiClient } from "../../lib/session";

interface ApprovalActionRow {
  action_id?: string;
  title?: string;
  assignee?: string | null;
  department?: string | null;
  due_date?: string | null;
  approval_reasons?: string[];
}

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [comment, setComment] = useState("");

  const refresh = useCallback(() => {
    apiClient()
      .listApprovals()
      .then(setApprovals)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "lỗi không rõ"),
      );
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function decide(approval: Approval, approve: boolean) {
    setBusyId(approval.id);
    setError(null);
    try {
      await apiClient().decideApproval(approval.id, { approve, comment });
      setComment("");
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <h1 className="text-2xl font-bold">Approval inbox</h1>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {approvals === null && !error && <p className="text-sm">Đang tải…</p>}
      {approvals?.length === 0 && (
        <p className="text-sm">Không có yêu cầu phê duyệt nào. ✨</p>
      )}

      {approvals?.map((approval) => {
        const actions = (approval.payload["actions"] ??
          []) as ApprovalActionRow[];
        return (
          <Card key={approval.id}>
            <CardHeader>
              <CardTitle className="text-base">
                {approval.approval_type}{" "}
                <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
                  {approval.status}
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p>{approval.reason}</p>
              {actions.length > 0 && (
                <ul className="space-y-1 rounded-md bg-slate-50 p-3 text-xs dark:bg-slate-800/50">
                  {actions.map((action, index) => (
                    <li key={index}>
                      <strong>{action.title}</strong> →{" "}
                      {action.assignee ?? "chưa xác định"}
                      {action.department ? ` (${action.department})` : ""}
                      {action.due_date
                        ? ` · hạn ${new Date(action.due_date).toLocaleDateString("vi-VN")}`
                        : ""}
                      {(action.approval_reasons?.length ?? 0) > 0 && (
                        <span className="ml-1 text-amber-600">
                          [{action.approval_reasons?.join(", ")}]
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              <input
                className="w-full rounded-md border border-slate-300 p-2 text-sm dark:border-slate-700 dark:bg-slate-950"
                placeholder="Ghi chú quyết định (tuỳ chọn)"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
              <div className="flex gap-2">
                <Button
                  onClick={() => void decide(approval, true)}
                  disabled={busyId === approval.id}
                >
                  {busyId === approval.id
                    ? "Đang xử lý…"
                    : "Phê duyệt & giao việc"}
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => void decide(approval, false)}
                  disabled={busyId === approval.id}
                >
                  Từ chối
                </Button>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
