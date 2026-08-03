"use client";

import { useEffect, useState } from "react";
import { BrainCircuit } from "lucide-react";
import type { MemoryItem } from "@dw/contracts";
import { Badge, Card, Skeleton } from "@dw/ui";
import { EmptyState } from "../../components/empty-state";
import { PageHeading } from "../../components/page-heading";
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
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeading
        eyebrow="Bộ nhớ có kiểm soát"
        icon={BrainCircuit}
        title="Trí nhớ dài hạn"
        description="Chỉ thông tin có nguồn bằng chứng rõ ràng và đáp ứng quy định mới được lưu vào lịch sử dài hạn."
      />
      {error && <p className="text-sm text-red-600">{error}</p>}
      {items === null && !error && <Skeleton className="h-56 rounded-2xl" />}
      {items?.length === 0 && (
        <EmptyState
          icon={BrainCircuit}
          title="Chưa có trí nhớ dài hạn"
          description="Các mục có bằng chứng sẽ xuất hiện sau khi hệ thống hoàn tất một quy trình phù hợp."
        />
      )}
      <div className="space-y-2">
        {items?.map((item) => (
          <Card key={item.memory_id} className="p-4 text-sm">
            <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-between">
              <Badge variant="secondary">
                {TYPE_LABELS[item.memory_type] ?? item.memory_type}
              </Badge>
              <span className="text-xs text-slate-500">
                tin cậy {(item.confidence * 100).toFixed(0)}% ·{" "}
                {item.provenance_count} bằng chứng
              </span>
            </div>
            <p className="mt-2">{item.content}</p>
            <p className="mt-1 text-xs text-slate-400">
              Mã lần xử lý: {item.created_by_run_id}
            </p>
          </Card>
        ))}
      </div>
    </div>
  );
}
