"use client";

import { useEffect, useState } from "react";
import type { KnowledgeDocument } from "@dw/contracts";
import { apiClient } from "../../lib/session";

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<KnowledgeDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient()
      .listKnowledgeDocuments()
      .then(setDocuments)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "lỗi không rõ"),
      );
  }, []);

  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Knowledge</h1>
        <p className="text-xs text-slate-500">
          Tài liệu đã ingest vào chỉ mục tri thức của tenant (Qdrant + Postgres,
          luôn kèm tenant filter)
        </p>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {documents === null && !error && <p className="text-sm">Đang tải…</p>}
      {documents?.length === 0 && (
        <p className="text-sm">
          Chưa có tài liệu nào — chạy phân tích hồ sơ thầu để ingest.
        </p>
      )}
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Tài liệu</th>
              <th className="px-3 py-2">Domain</th>
              <th className="px-3 py-2">Phân loại</th>
              <th className="px-3 py-2">Chunks</th>
              <th className="px-3 py-2">Index version</th>
              <th className="px-3 py-2">Ingest lúc</th>
            </tr>
          </thead>
          <tbody>
            {documents?.map((doc) => (
              <tr
                key={doc.document_id}
                className="border-t border-slate-100 dark:border-slate-800"
              >
                <td className="px-3 py-2 font-medium">{doc.title}</td>
                <td className="px-3 py-2">{doc.domain}</td>
                <td className="px-3 py-2 text-xs">{doc.classification}</td>
                <td className="px-3 py-2">{doc.chunk_count}</td>
                <td className="px-3 py-2 font-mono text-xs">
                  {doc.index_version ?? "—"}
                </td>
                <td className="px-3 py-2 text-xs">
                  {new Date(doc.created_at).toLocaleString("vi-VN")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
