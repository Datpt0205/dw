"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  Library,
  Loader2,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import type { KnowledgeDocument } from "@dw/contracts";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  Input,
  Select,
  Skeleton,
} from "@dw/ui";
import { EmptyState } from "../../components/empty-state";
import { PageHeading } from "../../components/page-heading";
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
  { value: "template", label: "Biểu mẫu" },
  { value: "shared", label: "Tài liệu dùng chung" },
];

const DOMAIN_LABEL = Object.fromEntries(
  DOMAINS.map((item) => [item.value, item.label]),
);

export default function KnowledgePage() {
  const [session, setSession] = useState<Session | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [domain, setDomain] = useState("legal");
  const [scope, setScope] = useState<"tenant" | "global">("tenant");
  const [formOpen, setFormOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const canWrite = hasScope(session, "knowledge.write");
  const canGlobal = hasRole(session, "platform_admin");

  const refresh = useCallback(() => {
    apiClient()
      .listKnowledgeDocuments()
      .then((rows) => {
        setDocuments(rows);
        setError(null);
      })
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : "Lỗi không rõ"),
      );
  }, []);

  useEffect(() => {
    setSession(loadSession());
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!formOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) setFormOpen(false);
    };
    window.addEventListener("keydown", onEscape);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onEscape);
    };
  }, [busy, formOpen]);

  const visibleDocuments = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("vi");
    return (documents ?? []).filter(
      (item) =>
        !query ||
        item.title.toLocaleLowerCase("vi").includes(query) ||
        item.domain.toLocaleLowerCase("vi").includes(query),
    );
  }, [documents, search]);

  async function pollJob(jobId: string): Promise<void> {
    for (let index = 0; index < 150; index += 1) {
      const job = await apiClient().getIngestJob(jobId);
      if (job.status === "done") {
        setProgress(
          `Hoàn tất: ${job.chunk_count ?? 0} đoạn nội dung đã sẵn sàng để tra cứu.`,
        );
        return;
      }
      if (job.status === "failed") {
        throw new Error(job.error ?? "Không thể xử lý tài liệu");
      }
      setProgress(`Đang xử lý (${job.status})…`);
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    setProgress("Vẫn đang xử lý — tải lại danh sách sau ít phút.");
  }

  async function onUpload(event: React.FormEvent) {
    event.preventDefault();
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
      setTitle("");
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setFormOpen(false);
      refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload lỗi");
      setProgress(null);
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(document: KnowledgeDocument) {
    if (
      !confirm(`Xoá tài liệu "${document.title}"? (xoá mềm, có thể phục hồi)`)
    )
      return;
    setBusy(true);
    try {
      await apiClient().deleteKnowledgeDocument(document.document_id);
      refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Xoá lỗi");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-[1320px] space-y-6">
      <PageHeading
        eyebrow="Nguồn tham chiếu"
        icon={Library}
        title="Tài liệu và nguồn tri thức"
        description="Quản lý luật, quy chế và biểu mẫu được hệ thống dùng để đối chiếu khi phân tích hồ sơ. Mỗi tài liệu đều có phạm vi truy cập và phiên bản rõ ràng."
        actions={
          canWrite && (
            <Button onClick={() => setFormOpen(true)}>
              <Upload /> Thêm tài liệu
            </Button>
          )
        }
      />

      {error && (
        <Alert variant="destructive">
          <p>{error}</p>
        </Alert>
      )}

      <section className="space-y-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="font-semibold">Danh mục tài liệu</h2>
              <p className="text-xs text-muted-foreground">
                Luật, quy chế và biểu mẫu đang được sử dụng
              </p>
            </div>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground" />
              <Input
                className="pl-9 sm:w-64"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Tìm theo tên hoặc loại…"
              />
            </div>
          </div>

          {documents === null && !error && (
            <Skeleton className="h-64 rounded-2xl" />
          )}
          {documents !== null && visibleDocuments.length === 0 && (
            <EmptyState
              icon={Library}
              title={
                documents.length === 0
                  ? "Kho tri thức đang trống"
                  : "Không tìm thấy tài liệu"
              }
              description={
                documents.length === 0
                  ? "Tải tài liệu đầu tiên để hệ thống có nguồn tham chiếu."
                  : "Thử thay đổi từ khóa tìm kiếm."
              }
            />
          )}
          {visibleDocuments.length > 0 && (
            <Card className="overflow-hidden">
              <div className="divide-y">
                {visibleDocuments.map((document) => (
                  <div
                    key={document.document_id}
                    className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:px-6"
                  >
                    <div className="flex min-w-0 items-start gap-3">
                      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
                        <BookOpen className="size-4" />
                      </span>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold">
                          {document.title}
                        </p>
                        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                          <span>
                            {DOMAIN_LABEL[document.domain] ?? document.domain}
                          </span>
                          <span>·</span>
                          <span>
                            {document.chunk_count} đoạn nội dung có thể tra cứu
                          </span>
                          <span>·</span>
                          <span>
                            {new Date(document.created_at).toLocaleDateString(
                              "vi-VN",
                            )}
                          </span>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          <Badge
                            variant={
                              document.scope === "global"
                                ? "warning"
                                : "secondary"
                            }
                          >
                            {document.scope === "global"
                              ? "Toàn cục"
                              : "Nội bộ"}
                          </Badge>
                          <Badge variant="outline">
                            Phiên bản {document.source_version}
                          </Badge>
                        </div>
                      </div>
                    </div>
                    {canWrite && (document.scope !== "global" || canGlobal) && (
                      <Button
                        variant="ghost"
                        size="icon"
                        title="Xoá tài liệu"
                        disabled={busy}
                        onClick={() => void onDelete(document)}
                        className="text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                      >
                        <Trash2 />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}
        </section>

      {canWrite && formOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6"
          role="dialog"
          aria-modal="true"
          aria-labelledby="add-doc-title"
        >
          <button
            type="button"
            className="absolute inset-0 bg-[#071d33]/55 backdrop-blur-[2px]"
            aria-label="Đóng cửa sổ thêm tài liệu"
            onClick={() => {
              if (!busy) setFormOpen(false);
            }}
          />
          <Card className="relative z-10 flex max-h-[92vh] w-full max-w-md flex-col overflow-hidden border-0 shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b bg-slate-50/90 px-5 py-4 sm:px-6">
              <div className="min-w-0">
                <h2 id="add-doc-title" className="font-semibold">
                  Thêm tài liệu
                </h2>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  Hỗ trợ PDF, DOCX, XLSX, PPTX và ảnh scan có OCR.
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                title="Đóng"
                disabled={busy}
                onClick={() => setFormOpen(false)}
              >
                <X />
              </Button>
            </div>
            <CardContent className="overflow-y-auto pt-5">
              <form id="add-doc-form" onSubmit={onUpload} className="space-y-5">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="group flex min-h-36 w-full flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50/60 px-5 text-center transition-colors hover:border-primary/50 hover:bg-[#edf5fa]"
                >
                  <span className="flex size-11 items-center justify-center rounded-2xl bg-white text-slate-600 shadow-sm group-hover:text-primary">
                    <Upload className="size-5" />
                  </span>
                  <span className="mt-3 max-w-full truncate text-sm font-semibold">
                    {file ? file.name : "Chọn hoặc kéo thả file"}
                  </span>
                  <span className="mt-1 text-xs text-muted-foreground">
                    PDF, DOCX, XLSX, PPTX, ảnh scan · tối đa 50&nbsp;MB
                  </span>
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  className="sr-only"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                />

                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium">
                    Tiêu đề <span className="text-destructive">*</span>
                  </span>
                  <Input
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder="Ví dụ: Luật Đấu thầu 2023"
                  />
                </label>
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="block">
                    <span className="mb-1.5 block text-sm font-medium">
                      Loại tài liệu
                    </span>
                    <Select
                      value={domain}
                      onChange={(event) => setDomain(event.target.value)}
                    >
                      {DOMAINS.map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </Select>
                  </label>
                  <label className="block">
                    <span className="mb-1.5 block text-sm font-medium">
                      Phạm vi truy cập
                    </span>
                    <Select
                      value={scope}
                      onChange={(event) =>
                        setScope(event.target.value as "tenant" | "global")
                      }
                    >
                      <option value="tenant">Nội bộ đơn vị</option>
                      <option value="global" disabled={!canGlobal}>
                        Dùng chung{canGlobal ? "" : " — cần quản trị"}
                      </option>
                    </Select>
                  </label>
                </div>

                {progress && (
                  <p className="rounded-lg bg-[#e7f0f7] px-3 py-2 text-xs leading-5 text-primary">
                    {progress}
                  </p>
                )}
              </form>
            </CardContent>
            <div className="flex items-center justify-end gap-2 border-t bg-slate-50/80 px-5 py-3.5 sm:px-6">
              <Button
                variant="ghost"
                onClick={() => setFormOpen(false)}
                disabled={busy}
              >
                Huỷ
              </Button>
              <Button
                type="submit"
                form="add-doc-form"
                disabled={busy || !file || !title.trim()}
              >
                {busy ? <Loader2 className="animate-spin" /> : <Upload />}
                {busy ? "Đang xử lý…" : "Tải lên và xử lý"}
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
