"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  BadgeCheck,
  CircleX,
  ClipboardCheck,
  History,
  Hourglass,
} from "lucide-react";
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
  Skeleton,
} from "@dw/ui";
import { EmptyState } from "./empty-state";
import { PageHeading } from "./page-heading";
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
    ? { label: "Chuẩn bị hồ sơ thầu", className: "bg-[#e7f0f7] text-primary" }
    : approvalType.startsWith("tender.")
      ? { label: "Đánh giá đấu thầu", className: "bg-[#e7f0f7] text-primary" }
      : approvalType.startsWith("work_ops.")
        ? { label: "Cuộc họp", className: "bg-emerald-50 text-emerald-700" }
        : null;

function approvalTitle(approvalType: string) {
  const titles: Record<string, string> = {
    "preparation.cp1": "Phê duyệt phương án lựa chọn nhà thầu",
    "preparation.cp2": "Phê duyệt hồ sơ mời thầu",
    "tender.approve_recommendation": "Phê duyệt đề xuất lựa chọn",
  };
  return titles[approvalType] ?? "Yêu cầu phê duyệt";
}

function approvalStep(value: unknown) {
  const steps: Record<string, string> = {
    CP1: "Bước 1 — Phương án lựa chọn",
    CP2: "Bước 2 — Hồ sơ mời thầu",
    CP3: "Bước 3 — Thay đổi hồ sơ",
    CP4: "Bước 4 — Mở thầu",
    DW01: "Chuẩn bị hồ sơ thầu",
  };
  const key = String(value ?? "DW01");
  return steps[key] ?? key;
}

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
  const [comments, setComments] = useState<Record<string, string>>({});
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
    const comment = comments[approval.id] ?? "";
    setBusyId(approval.id);
    setError(null);
    try {
      await apiClient().decideApproval(approval.id, { approve, comment });
      setComments((current) => ({ ...current, [approval.id]: "" }));
      toast.success(
        approve
          ? "Đã phê duyệt — hồ sơ sẽ chuyển sang bước tiếp theo."
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
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeading
        eyebrow="Kiểm soát phê duyệt"
        icon={ClipboardCheck}
        title="Hàng chờ phê duyệt"
        description="Các hồ sơ đang chờ quyết định được ưu tiên ở trên. Hãy xem tài liệu liên quan và ghi rõ nhận xét trước khi phê duyệt."
      />
      {error && <p className="text-sm text-destructive">{error}</p>}
      {approvals === null && !error && (
        <Skeleton className="h-64 rounded-2xl" />
      )}

      {approvals !== null && pending.length === 0 && (
        <EmptyState
          icon={Hourglass}
          title="Không có yêu cầu đang chờ"
          description={emptyHint}
        />
      )}

      {pending.map((approval) => {
        const actions = (approval.payload["actions"] ??
          []) as ApprovalActionRow[];
        const badge = STATUS_BADGE[approval.status];
        const isPreparation = approval.approval_type.startsWith("preparation.");
        const gate = approval.payload["gate"] as
          { passed?: boolean; reasons?: string[] } | undefined;
        const preparationCaseId = approval.payload["case_id"];
        return (
          <Card key={approval.id} className="overflow-hidden border-amber-200">
            <CardHeader className="border-b bg-amber-50/60">
              <CardTitle className="flex flex-col items-start gap-3 text-base sm:flex-row sm:items-center sm:justify-between">
                <span className="flex min-w-0 flex-wrap items-center gap-2">
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
                  <span>{approvalTitle(approval.approval_type)}</span>
                </span>
                <Badge variant={badge.variant}>{badge.label}</Badge>
              </CardTitle>
              <CardDescription>{approval.reason}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 pt-5 text-sm">
              {isPreparation && (
                <div className="grid gap-3 rounded-lg border bg-[#edf5fa] p-4 md:grid-cols-2">
                  <div>
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      Bước phê duyệt
                    </p>
                    <p className="font-semibold">
                      {approvalStep(approval.payload["checkpoint"])}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      Giá trị gói
                    </p>
                    <p className="font-semibold">
                      {String(approval.payload["estimated_value"] ?? "—")}
                    </p>
                  </div>
                  {approval.payload["method"] != null && (
                    <div>
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">
                        Hình thức
                      </p>
                      <p className="font-medium">
                        {String(
                          (approval.payload["method"] as { label?: unknown })
                            .label ?? "—",
                        )}
                      </p>
                    </div>
                  )}
                  <div>
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      Kết quả kiểm tra điều kiện
                    </p>
                    <Badge variant={gate?.passed ? "success" : "destructive"}>
                      {gate?.passed ? "Đạt" : "Không đạt"}
                    </Badge>
                  </div>
                  {gate?.reasons && gate.reasons.length > 0 && (
                    <ul className="list-disc pl-5 text-xs text-destructive md:col-span-2">
                      {gate.reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                  )}
                  {typeof preparationCaseId === "string" && (
                    <Link
                      className="text-xs font-medium text-primary underline md:col-span-2"
                      href={`/procurement/dw01/cases/${preparationCaseId}`}
                    >
                      Mở hồ sơ và toàn bộ bằng chứng trước khi quyết định
                    </Link>
                  )}
                </div>
              )}
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
                  <div className="rounded-xl border bg-slate-50 p-4">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                      Quyết định của bạn
                    </p>
                    <Input
                      placeholder={
                        isPreparation
                          ? "Nhận xét kiểm tra (bắt buộc với DW01)"
                          : "Ghi chú quyết định (tuỳ chọn)"
                      }
                      value={comments[approval.id] ?? ""}
                      onChange={(e) =>
                        setComments((current) => ({
                          ...current,
                          [approval.id]: e.target.value,
                        }))
                      }
                    />
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        onClick={() => void decide(approval, true)}
                        disabled={
                          busyId === approval.id ||
                          (isPreparation &&
                            !(comments[approval.id] ?? "").trim())
                        }
                      >
                        <BadgeCheck />
                        {busyId === approval.id ? "Đang xử lý…" : "Phê duyệt"}
                      </Button>
                      <Button
                        variant="destructive"
                        onClick={() => void decide(approval, false)}
                        disabled={
                          busyId === approval.id ||
                          (isPreparation &&
                            !(comments[approval.id] ?? "").trim())
                        }
                      >
                        <CircleX /> Từ chối
                      </Button>
                    </div>
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
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <History className="size-4 text-muted-foreground" />
            Lịch sử quyết định gần đây
          </h2>
          <div className="space-y-2">
            {decided.slice(0, 8).map((approval) => {
              const badge = STATUS_BADGE[approval.status];
              return (
                <div
                  key={approval.id}
                  className="flex items-center justify-between gap-4 rounded-xl border bg-card px-4 py-3 text-sm"
                >
                  <div>
                    <span className="font-medium">
                      {approval.approval_type}
                    </span>
                    <p className="text-xs text-muted-foreground">
                      {approval.reason}
                    </p>
                  </div>
                  <Badge variant={badge.variant}>{badge.label}</Badge>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
