"use client";

import { useEffect, useState } from "react";
import type { SupplierScore, TenderCase } from "@dw/contracts";
import { apiClient } from "../../../lib/session";

interface SupplierRow extends SupplierScore {
  caseTitle: string;
}

export default function SuppliersPage() {
  const [rows, setRows] = useState<SupplierRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const client = apiClient();
    client
      .listTenderCases()
      .then(async (cases: TenderCase[]) => {
        const detailed = await Promise.all(
          cases.map((c) => client.getTenderCase(c.id)),
        );
        setRows(
          detailed.flatMap(
            (c) =>
              c.recommendation?.supplier_scores.map((s) => ({
                ...s,
                caseTitle: c.title,
              })) ?? [],
          ),
        );
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "lỗi không rõ"),
      );
  }, []);

  return (
    <div className="max-w-4xl space-y-6">
      <h1 className="text-2xl font-bold">Nhà cung cấp đã đánh giá</h1>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {rows === null && !error && <p className="text-sm">Đang tải…</p>}
      {rows?.length === 0 && <p className="text-sm">Chưa có đánh giá nào.</p>}
      <div className="space-y-2">
        {rows?.map((row, index) => (
          <div
            key={index}
            className="rounded-lg border border-slate-200 bg-white p-3 text-sm dark:border-slate-800 dark:bg-slate-900"
          >
            <div className="flex items-center justify-between">
              <span className="font-medium">{row.supplier_name}</span>
              <span className="font-mono">{row.total_score} điểm</span>
            </div>
            <p className="text-xs text-slate-500">
              {row.caseTitle} · {row.eligible ? "đủ điều kiện" : "bị loại"}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
