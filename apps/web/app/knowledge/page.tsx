"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { KnowledgeDocument } from "@dw/contracts";
import { apiClient } from "../../lib/session";
import {
  hasRole,
  hasScope,
  loadSession,
  type Session,
} from "../../lib/session";

const DOMAINS = [
  { value: "legal", label: "Pháp lý / Luật" },
  { value: "policy", label: "Quy chế nội bộ" },
  { value: "template", label: "Biểu mẫu / Template" },
  { value: "shared", label: "Chung" },
];

export default function KnowledgePage() {
  const [session, setSession] = useState<Session | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);

  // upload form state
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [domain, setDomain] = useState("legal");
  const [scope, setScope] = useState<"tenant" | "global">("tenant");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const canWrite = hasScope(session, "knowledge.write");
  const canGlobal = hasRole(session, "platform_admin");

  const refresh = useCallback(() => {
    apiClient()
      .listKnowledgeDocuments()
      .then(setDocuments)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "lỗi không rõ"),
      );
  }, []);

  useEffect(() => {
    setSession(loadSession());
    refresh();
  }, [refresh]);

  async function pollJob(jobId: string): Promise<void> {
    // Async ingest: poll the job until the worker finishes parse→chunk→embed→index.
    for (let i = 0; i < 150; i += 1) {
      const job = await apiClient().getIngestJob(jobId);
      if (job.status === "done") {
        setProgress(`Hoàn tất: ${job.chunk_count ?? 0} chunk đã lập chỉ mục.`);
        return;
      }
      if (job.status === "failed") {
        throw new Error(job.error ?? "ingest thất bại");
      }
      setProgress(`Đang xử lý (${job.status})…`);
      await new Promise((r) => setTimeout(r, 2000));
    }
    setProgress("Vẫn đang xử lý — tải lại danh sách sau ít phút.");
  }

  async function onUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !title.trim()) {
      setError("Cần chọn file và nhập tiêu đề.");
      return;
    }
    setBusy(true);
    setError(null);
    setProgress("Đang tải lên…");
    try {
      const job = await apiClient().uploadKnowledgeDocument(file, {
        title: title.trim(),
        domain,
        scope,
      });
      await pollJob(job.job_id);
      // reset form + refresh inventory
      setTitle("");
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "upload lỗi");
      setProgress(null);
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(doc: KnowledgeDocument) {
    if (!confirm(`Xoá tài liệu "${doc.title}"? (xoá mềm, có thể phục hồi)`)) return;
    setBusy(true);
    try {
      await apiClient().deleteKnowledgeDocument(doc.document_id);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "xoá lỗi");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Knowledge</h1>
        <p className="text-xs text-slate-500">
          Tài liệu tri thức (Qdrant + Postgres, luôn kèm tenant filter). Luật pháp
          lý dùng phạm vi <b>global</b> — mọi tenant đều đọc được; quy chế/biểu mẫu
          để <b>tenant</b> — chỉ tổ chức của bạn thấy.
        </p>
      </div>

      {canWrite && (
        <form
          onSubmit={onUpload}
          className="space-y-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
        >
          <h2 className="text-sm font-semibold">Tải tài liệu lên</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-xs">
              <span className="text-slate-500">Tiêu đề</span>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="VD: Luật Đấu thầu 2023"
                className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </label>
            <label className="space-y-1 text-xs">
              <span className="text-slate-500">Loại tài liệu</span>
              <select
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
              >
                {DOMAINS.map((d) => (
                  <option key={d.value} value={d.value}>
                    {d.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-xs">
              <span className="text-slate-500">
                File (PDF, DOCX, XLSX, PPTX, ảnh scan… — có OCR)
              </span>
              <input
                ref={fileInputRef}
                type="file"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="w-full text-sm"
              />
            </label>
            <label className="space-y-1 text-xs">
              <span className="text-slate-500">Phạm vi</span>
              <select
                value={scope}
                onChange={(e) => setScope(e.target.value as "tenant" | "global")}
                className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
              >
                <option value="tenant">Tenant (nội bộ tổ chức)</option>
                <option value="global" disabled={!canGlobal}>
                  Global — luật dùng chung {canGlobal ? "" : "(cần platform_admin)"}
                </option>
              </select>
            </label>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={busy}
              className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
            >
              {busy ? "Đang xử lý…" : "Tải lên & ingest"}
            </button>
            {progress && <span className="text-xs text-slate-500">{progress}</span>}
          </div>
        </form>
      )}

      {error && <p className="text-sm text-red-600">{error}</p>}
      {documents === null && !error && <p className="text-sm">Đang tải…</p>}
      {documents?.length === 0 && (
        <p className="text-sm">Chưa có tài liệu nào — tải lên ở trên để ingest.</p>
      )}

      {documents && documents.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Tài liệu</th>
                <th className="px-3 py-2">Phạm vi</th>
                <th className="px-3 py-2">Domain</th>
                <th className="px-3 py-2">Chunks</th>
                <th className="px-3 py-2">Ver</th>
                <th className="px-3 py-2">Ingest lúc</th>
                {canWrite && <th className="px-3 py-2"></th>}
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr
                  key={doc.document_id}
                  className="border-t border-slate-100 dark:border-slate-800"
                >
                  <td className="px-3 py-2 font-medium">{doc.title}</td>
                  <td className="px-3 py-2">
                    <span
                      className={
                        doc.scope === "global"
                          ? "rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
                          : "rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                      }
                    >
                      {doc.scope === "global" ? "global" : "tenant"}
                    </span>
                  </td>
                  <td className="px-3 py-2">{doc.domain}</td>
                  <td className="px-3 py-2">{doc.chunk_count}</td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {doc.source_version}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {new Date(doc.created_at).toLocaleString("vi-VN")}
                  </td>
                  {canWrite && (
                    <td className="px-3 py-2 text-right">
                      {/* Global docs are shared; only platform_admin may remove them. */}
                      {(doc.scope !== "global" || canGlobal) && (
                        <button
                          onClick={() => onDelete(doc)}
                          disabled={busy}
                          className="text-xs text-red-600 hover:underline disabled:opacity-50"
                        >
                          Xoá
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
