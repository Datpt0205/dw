"use client";

import { useEffect, useState } from "react";
import type { MemoryItem } from "@dw/contracts";
import { apiClient } from "../../lib/session";

const TYPE_LABELS: Record<string, string> = {
  episodic: "Sự kiện",
  semantic: "Tri thức",
  procedural: "Quy trình",
  preference: "Sở thích",
  commitment: "Cam kết",
};

export default function MemoryPage() {
  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient()
      .listMemoryItems()
      .then(setItems)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "lỗi không rõ"),
      );
  }, []);

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Memory</h1>
        <p className="text-xs text-slate-500">
          Trí nhớ dài hạn đã qua policy (chỉ fact có provenance mới được ghi;
          model không bao giờ ghi trực tiếp)
        </p>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {items === null && !error && <p className="text-sm">Đang tải…</p>}
      {items?.length === 0 && (
        <p className="text-sm">
          Chưa có memory nào — chạy một worker để sinh trí nhớ.
        </p>
      )}
      <div className="space-y-2">
        {items?.map((item) => (
          <div
            key={item.memory_id}
            className="rounded-lg border border-slate-200 bg-white p-3 text-sm dark:border-slate-800 dark:bg-slate-900"
          >
            <div className="flex items-center justify-between">
              <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium dark:bg-slate-800">
                {TYPE_LABELS[item.memory_type] ?? item.memory_type} ·{" "}
                {item.worker_id}
              </span>
              <span className="text-xs text-slate-500">
                tin cậy {(item.confidence * 100).toFixed(0)}% ·{" "}
                {item.provenance_count} bằng chứng
              </span>
            </div>
            <p className="mt-2">{item.content}</p>
            <p className="mt-1 font-mono text-xs text-slate-400">
              run {item.created_by_run_id}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
