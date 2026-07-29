"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, FileCheck2 } from "lucide-react";
import type { PreparationCase } from "@dw/api-client";
import { Badge, Card, CardContent } from "@dw/ui";
import { useAuth } from "../lib/auth/auth-context";
import { apiClient } from "../lib/session";
import { formatVnd } from "../app/procurement/dw01/state";

/**
 * Cases sitting at "chờ xác minh intake" (state=draft) that an approver must
 * verify on the case page. Surfaced on the Approvals screen so the approver has
 * one place to see everything waiting on them — intake verification does not go
 * through the CP1–CP4 approval queue.
 */
export function PendingIntakeVerification() {
  const { hasScope } = useAuth();
  const canVerify = hasScope("approvals.decide");
  const [cases, setCases] = useState<PreparationCase[] | null>(null);

  const refresh = useCallback(() => {
    if (!canVerify) {
      setCases([]);
      return;
    }
    apiClient()
      .listPreparationCases()
      .then((rows) => setCases(rows.filter((row) => row.state === "draft")))
      .catch(() => setCases([]));
  }, [canVerify]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll every 5s + refresh on focus/reveal so a newly created case shows up
  // for the verifier's tab promptly.
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

  if (!canVerify || cases === null || cases.length === 0) return null;

  return (
    <Card className="border-amber-200 bg-amber-50/40">
      <div className="flex items-center gap-2 border-b border-amber-200/70 px-5 py-4 sm:px-6">
        <FileCheck2 className="size-4 text-amber-600" />
        <h2 className="font-semibold">Hồ sơ chờ bạn xác minh đầu vào</h2>
        <Badge variant="warning">{cases.length}</Badge>
      </div>
      <CardContent className="pt-3">
        <p className="pb-2 text-xs text-muted-foreground">
          Bước xác minh nằm trong từng hồ sơ (không qua hàng chờ CP1–CP4). Mở hồ
          sơ để xác minh trước khi Digital Worker chạy.
        </p>
        <div className="divide-y divide-amber-200/60">
          {cases.map((item) => (
            <Link
              key={item.id}
              href={`/procurement/dw01/cases/${item.id}`}
              className="group flex items-center gap-4 py-3 first:pt-0 last:pb-0"
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-700">
                <FileCheck2 className="size-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold group-hover:text-primary">
                  {item.title}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {item.source_pr_ref} · {formatVnd(item.estimated_value_minor)}{" "}
                  · người lập {item.owner_name}
                </span>
              </span>
              <span className="hidden shrink-0 text-xs font-semibold text-primary sm:inline">
                Mở để xác minh
              </span>
              <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
            </Link>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
