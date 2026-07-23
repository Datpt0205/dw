"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { TenderCase } from "@dw/contracts";
import { apiClient } from "../../../lib/session";

export default function EvaluationsPage() {
  const [cases, setCases] = useState<TenderCase[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient()
      .listTenderCases()
      .then((all) => setCases(all.filter((c) => c.status === "completed")))
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "lỗi không rõ"),
      );
  }, []);

  return (
    <div className="max-w-4xl space-y-6">
      <h1 className="text-2xl font-bold">Đánh giá đã hoàn tất</h1>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {cases === null && !error && <p className="text-sm">Đang tải…</p>}
      {cases?.length === 0 && (
        <p className="text-sm">Chưa có đánh giá nào hoàn tất.</p>
      )}
      <div className="space-y-2">
        {cases?.map((tenderCase) => (
          <Link
            key={tenderCase.id}
            href={`/procurement/cases/${tenderCase.id}`}
            className="block rounded-lg border border-slate-200 bg-white p-3 text-sm hover:border-slate-400 dark:border-slate-800 dark:bg-slate-900"
          >
            <span className="font-medium">{tenderCase.title}</span>
            {tenderCase.export_ref && (
              <p className="font-mono text-xs text-slate-500">
                {tenderCase.export_ref}
              </p>
            )}
          </Link>
        ))}
      </div>
    </div>
  );
}
