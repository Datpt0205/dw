"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { FileEdit } from "lucide-react";
import { toast } from "sonner";
import type { PreparationCase } from "@dw/api-client";
import { Badge, Button, Card, CardContent, Input } from "@dw/ui";
import { useAuth } from "../lib/auth/auth-context";
import { DW01_READONLY } from "../lib/readonly";
import { apiClient } from "../lib/session";
import { formatVnd } from "../app/procurement/dw01/state";

/**
 * Cases waiting for a CP3 (addendum) decision. Kept on the Approvals screen so
 * every checkpoint decision lives in one place, consistent with CP1/CP2 — even
 * though CP3 is a domain endpoint, not a LangGraph interrupt.
 */
export function PendingCp3Decision() {
  const { hasScope } = useAuth();
  // Read-only back office: CP3 is decided on the Slack card.
  const canDecide = hasScope("approvals.decide") && !DW01_READONLY;
  const [cases, setCases] = useState<PreparationCase[] | null>(null);
  const [refs, setRefs] = useState<Record<string, string>>({});
  const [comments, setComments] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (!canDecide) {
      setCases([]);
      return;
    }
    apiClient()
      .listPreparationCases()
      .then((rows) => setCases(rows.filter((r) => r.state === "cp3_pending")))
      .catch(() => setCases([]));
  }, [canDecide]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === "visible") refresh();
    };
    const id = setInterval(tick, 5000);
    document.addEventListener("visibilitychange", tick);
    window.addEventListener("focus", tick);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
      window.removeEventListener("focus", tick);
    };
  }, [refresh]);

  async function decide(id: string, approve: boolean) {
    setBusyId(id);
    try {
      await apiClient().decidePreparationCp3(id, {
        approve,
        approval_reference: refs[id] ?? "",
        comment: comments[id] ?? "",
      });
      toast.success(
        approve ? "Đã duyệt sửa đổi (CP3)." : "Đã từ chối addendum.",
      );
      refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Lỗi không rõ");
    } finally {
      setBusyId(null);
    }
  }

  if (!canDecide || cases === null || cases.length === 0) return null;

  return (
    <Card className="border-amber-200 bg-amber-50/40">
      <div className="flex items-center gap-2 border-b border-amber-200/70 px-5 py-4 sm:px-6">
        <FileEdit className="size-4 text-amber-600" />
        <h2 className="font-semibold">
          Hồ sơ chờ bạn quyết định sửa đổi (CP3)
        </h2>
        <Badge variant="warning">{cases.length}</Badge>
      </div>
      <CardContent className="space-y-3 pt-3">
        <p className="text-xs text-muted-foreground">
          Văn bản sửa đổi/làm rõ HSMT sau phát hành. Người tạo hồ sơ không được
          tự quyết định (SoD).
        </p>
        {cases.map((item) => (
          <div key={item.id} className="rounded-lg border bg-background p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold">{item.title}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {item.source_pr_ref} · {formatVnd(item.estimated_value_minor)}
                </p>
              </div>
              <Link
                href={`/procurement/dw01/cases/${item.id}`}
                className="shrink-0 text-xs font-semibold text-primary hover:underline"
              >
                Mở hồ sơ xem nội dung sửa đổi
              </Link>
            </div>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              <Input
                placeholder="Mã phê duyệt CP3"
                value={refs[item.id] ?? ""}
                onChange={(e) =>
                  setRefs((c) => ({ ...c, [item.id]: e.target.value }))
                }
              />
              <Input
                placeholder="Nhận xét (tuỳ chọn)"
                value={comments[item.id] ?? ""}
                onChange={(e) =>
                  setComments((c) => ({ ...c, [item.id]: e.target.value }))
                }
              />
            </div>
            <div className="mt-2 flex gap-2">
              <Button
                onClick={() => void decide(item.id, true)}
                disabled={busyId === item.id || !(refs[item.id] ?? "").trim()}
              >
                Duyệt CP3
              </Button>
              <Button
                variant="destructive"
                onClick={() => void decide(item.id, false)}
                disabled={busyId === item.id || !(refs[item.id] ?? "").trim()}
              >
                Từ chối
              </Button>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
