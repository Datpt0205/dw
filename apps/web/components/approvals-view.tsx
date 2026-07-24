"use client";

import { useCallback, useEffect, useState } from "react";
import { BadgeCheck, CircleX, Hourglass } from "lucide-react";
import { toast } from "sonner";
import type { Approval } from "@dw/contracts";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Separator,
} from "@dw/ui";
import { useAuth } from "../lib/auth/auth-context";
import { apiClient } from "../lib/session";

interface ApprovalActionRow {
  action_id?: string;
  title?: string;
  assignee?: string | null;
  department?: string | null;
  due_date?: string | null;
  approval_reasons?: string[];
}

const STATUS_BADGE: Record<
  Approval["status"],
  {
    label: string;
    variant: "warning" | "success" | "destructive" | "secondary";
  }
> = {
  pending: { label: "chờ duyệt", variant: "warning" },
  approved: { label: "đã duyệt", variant: "success" },
  rejected: { label: "đã từ chối", variant: "destructive" },
  cancelled: { label: "đã huỷ", variant: "secondary" },
};

const MODULE_LABEL = (approvalType: string) =>
  approvalType.startsWith("preparation.")
    ? { label: "Hồ sơ thầu (DW01)", className: "bg-blue-50 text-blue-700" }
    : approvalType.startsWith("tender.")
      ? { label: "Đấu thầu", className: "bg-blue-50 text-blue-700" }
      : approvalType.startsWith("work_ops.")
        ? { label: "Cuộc họp", className: "bg-emerald-50 text-emerald-700" }
        : null;

/** Approval inbox; optionally scoped by approval_type prefix. */
export function ApprovalsView({
  typePrefix,
  emptyHint,
}: {
  typePrefix?: string;
  emptyHint: string;
}) {
  const [approvals, setApprovals] = useState<Approval[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const { hasScope } = useAuth();
  const canDecide = hasScope("approvals.decide");

  const refresh = useCallback(() => {
    apiClient()
      .listApprovals()
      .then((all) =>
        setApprovals(
          typePrefix
            ? all.filter((a) => a.approval_type.startsWith(typePrefix))
            : all,
        ),
      )
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "lỗi không rõ"),
      );
  }, [typePrefix]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function decide(approval: Approval, approve: boolean) {
    setBusyId(approval.id);
    setError(null);
    try {
      await apiClient().decideApproval(approval.id, { approve, comment });
      setComment("");
      toast.success(
        approve
          ? "Đã phê duyệt — worker tiếp tục chạy và hoàn tất."
          : "Đã từ chối — không có hành động nào được thực hiện.",
      );
      refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : "lỗi không rõ";
      setError(message);
      toast.error(message);
    } finally {
      setBusyId(null);
    }
  }

  const pending = approvals?.filter((a) => a.status === "pending") ?? [];
  const decided = approvals?.filter((a) => a.status !== "pending") ?? [];

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Phê duyệt</h1>
        <p className="text-sm text-muted-foreground">
          Worker luôn dừng tại đây trước khi thực hiện hành động thật.
        </p>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}

      {approvals !== null && pending.length === 0 && (
        <Card>
          <CardContent className="flex items-center gap-3 pt-5 text-sm text-muted-foreground">
            <Hourglass className="size-4" />
            {emptyHint}
          </CardContent>
        </Card>
      )}

      {pending.map((approval) => {
        const actions = (approval.payload["actions"] ??
          []) as ApprovalActionRow[];
        const badge = STATUS_BADGE[approval.status];
        return (
          <Card key={approval.id} className="border-warning/50">
            <CardHeader>
              <CardTitle className="flex items-center justify-between text-base">
                <span className="flex items-center gap-2">
                  {(() => {
                    const moduleTag = MODULE_LABEL(approval.approval_type);
                    return moduleTag ? (
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-medium ${moduleTag.className}`}
                      >
                        {moduleTag.label}
                      </span>
                    ) : null;
                  })()}
                  {approval.approval_type}
                </span>
                <Badge variant={badge.variant}>{badge.label}</Badge>
              </CardTitle>
              <CardDescription>{approval.reason}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              {actions.length > 0 && (
                <div className="space-y-2 rounded-lg bg-muted/50 p-3">
                  {actions.map((action, index) => (
                    <div
                      key={index}
                      className="flex flex-wrap items-center gap-2 text-xs"
                    >
                      <span className="font-medium">{action.title}</span>
                      <span className="text-muted-foreground">
                        → {action.assignee ?? "chưa xác định"}
                        {action.department ? ` (${action.department})` : ""}
                        {action.due_date
                          ? ` · hạn ${new Date(action.due_date).toLocaleDateString("vi-VN")}`
                          : ""}
                      </span>
                      {action.approval_reasons?.map((reason) => (
                        <Badge key={reason} variant="warning">
                          {reason}
                        </Badge>
                      ))}
                    </div>
                  ))}
                </div>
              )}
              {!canDecide && (
                <p className="rounded-md bg-warning/10 px-3 py-2 text-xs text-warning">
                  Vai hiện tại không có quyền phê duyệt. Cần vai{" "}
                  <strong>Người phê duyệt</strong>.
                </p>
              )}
              {canDecide && (
                <>
                  <Input
                    placeholder="Ghi chú quyết định (tuỳ chọn)"
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                  />
                  <div className="flex gap-2">
                    <Button
                      onClick={() => void decide(approval, true)}
                      disabled={busyId === approval.id}
                    >
                      <BadgeCheck />
                      {busyId === approval.id ? "Đang xử lý…" : "Phê duyệt"}
                    </Button>
                    <Button
                      variant="destructive"
                      onClick={() => void decide(approval, false)}
                      disabled={busyId === approval.id}
                    >
                      <CircleX /> Từ chối
                    </Button>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        );
      })}

      {decided.length > 0 && (
        <>
          <Separator />
          <h2 className="text-sm font-medium text-muted-foreground">
            Đã quyết định gần đây
          </h2>
          <div className="space-y-2">
            {decided.slice(0, 8).map((approval) => {
              const badge = STATUS_BADGE[approval.status];
              return (
                <Card key={approval.id}>
                  <CardContent className="flex items-center justify-between pt-4 text-sm">
                    <div>
                      <span className="font-medium">
                        {approval.approval_type}
                      </span>
                      <p className="text-xs text-muted-foreground">
                        {approval.reason}
                      </p>
                    </div>
                    <Badge variant={badge.variant}>{badge.label}</Badge>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
