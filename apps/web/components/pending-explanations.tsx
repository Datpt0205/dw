"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { HeartHandshake } from "lucide-react";
import { toast } from "sonner";
import type { ReworkExplanation } from "@dw/api-client";
import { Button, Card, CardContent, Textarea } from "@dw/ui";
import { useAuth } from "../lib/auth/auth-context";
import { apiClient } from "../lib/session";

const REASON_LABEL: Record<string, string> = {
  missing_pr_evidence: "Thiếu căn cứ phê duyệt",
  budget_mismatch: "Ngân sách chưa khớp",
  supplier_shortfall: "Chưa đủ nhà cung cấp",
  criteria_issue: "Tiêu chí đánh giá chưa đạt",
  timeline_issue: "Mốc thời gian chưa hợp lệ",
  missing_documents: "Thiếu tài liệu kèm theo",
  other: "Nội dung khác cần chỉnh",
};

/**
 * People who cannot file a new case until somebody reads what they wrote.
 *
 * Oldest first, because the person at the front has been stuck longest — and
 * a queue nobody reads is the worst state the whole support mechanism can
 * produce. Every decision carries a note back to the author; the server
 * refuses one without it.
 */
export function PendingExplanations() {
  const { hasScope } = useAuth();
  const [rows, setRows] = useState<ReworkExplanation[] | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (!hasScope("approvals.decide")) {
      setRows([]);
      return;
    }
    apiClient()
      .listPendingReworkExplanations()
      .then(setRows)
      // A 409 here just means this account is not the supporting role.
      // Nothing to show, and nothing worth alarming anybody about.
      .catch(() => setRows([]));
  }, [hasScope]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (!rows || rows.length === 0) return null;

  async function decide(id: string, approve: boolean) {
    const comment = (notes[id] ?? "").trim();
    if (!comment) {
      toast.error("Cần một dòng phản hồi gửi lại người viết.");
      return;
    }
    setBusy(id);
    try {
      await apiClient().decideReworkExplanation(id, { approve, comment });
      toast.success(approve ? "Đã gỡ chặn và phản hồi." : "Đã gửi phản hồi.");
      refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Chưa gửi được.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div className="flex items-center gap-2">
          <HeartHandshake className="size-4 text-primary" />
          <h2 className="text-base font-semibold">
            Đang chờ hỗ trợ ({rows.length})
          </h2>
        </div>
        <p className="text-sm text-muted-foreground">
          Những người này đang chờ trao đổi trước khi tạo hồ sơ mới. Đọc phần mô
          tả, phản hồi một dòng, rồi gỡ chặn để họ làm tiếp.
        </p>
        {rows.map((row) => (
          <div key={row.id} className="space-y-3 rounded-lg border p-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>{row.block_count} hồ sơ phải chỉnh lại</span>
              {row.top_reason_code && (
                <span>
                  · Hay gặp:{" "}
                  {REASON_LABEL[row.top_reason_code] ?? row.top_reason_code}
                </span>
              )}
              {row.case_id && (
                <Link
                  className="text-primary underline"
                  href={`/procurement/dw01/cases/${row.case_id}`}
                >
                  Mở hồ sơ liên quan
                </Link>
              )}
            </div>
            <p className="whitespace-pre-wrap text-sm">{row.context_text}</p>
            {row.difficulty_text && (
              <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                Khó khăn: {row.difficulty_text}
              </p>
            )}
            {row.support_request_text && (
              <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                Mong hỗ trợ: {row.support_request_text}
              </p>
            )}
            <Textarea
              rows={2}
              placeholder="Phản hồi gửi lại người viết (bắt buộc)…"
              value={notes[row.id] ?? ""}
              onChange={(event) =>
                setNotes((current) => ({
                  ...current,
                  [row.id]: event.target.value,
                }))
              }
            />
            <div className="flex gap-2">
              <Button
                disabled={busy === row.id}
                onClick={() => void decide(row.id, true)}
              >
                Đã trao đổi — gỡ chặn
              </Button>
              <Button
                variant="outline"
                disabled={busy === row.id}
                onClick={() => void decide(row.id, false)}
              >
                Cần trao đổi thêm
              </Button>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
