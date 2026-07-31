"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowRight,
  FileText,
  Filter,
  FolderKanban,
  Search,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import { toast } from "sonner";
import type { PreparationCase } from "@dw/api-client";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  Input,
  Select,
  Skeleton,
  Textarea,
} from "@dw/ui";
import { EmptyState } from "../../../components/empty-state";
import { PageHeading } from "../../../components/page-heading";
import { TagInput } from "../../../components/tag-input";
import { useAuth } from "../../../lib/auth/auth-context";
import { DW01_READONLY } from "../../../lib/readonly";
import { apiClient } from "../../../lib/session";
import {
  BUSINESS_DOMAINS,
  businessDomainLabel,
  PROCUREMENT_TYPES,
  procurementTypeLabel,
} from "./catalog";
import { STATE_BADGE, formatVnd } from "./state";

// Group digits into VND thousands (2500000000 -> "2.500.000.000").
function formatThousands(digits: string): string {
  const clean = digits.replace(/\D/g, "").replace(/^0+(?=\d)/, "");
  return clean.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

// Human scale hint so a typo in the number of zeros is obvious before submit.
function vndInWords(digits: string): string {
  const n = Number(digits.replace(/\D/g, ""));
  if (!n) return "";
  if (n >= 1_000_000_000)
    return `${(n / 1_000_000_000).toLocaleString("vi-VN", { maximumFractionDigits: 2 })} tỷ đồng`;
  if (n >= 1_000_000)
    return `${(n / 1_000_000).toLocaleString("vi-VN", { maximumFractionDigits: 2 })} triệu đồng`;
  return `${n.toLocaleString("vi-VN")} đồng`;
}

export default function Dw01ListPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { hasScope } = useAuth();
  // Read-only back office: cases are created by chatting with the Digital
  // Worker in Slack; the web only tracks them.
  const canCreate = hasScope("tender.write") && !DW01_READONLY;
  const [cases, setCases] = useState<PreparationCase[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [reference, setReference] = useState("");
  const [value, setValue] = useState("");
  const [deadline, setDeadline] = useState("");
  const [owner, setOwner] = useState("");
  const [description, setDescription] = useState("");
  const [suppliers, setSuppliers] = useState<string[]>([]);
  const [procurementType, setProcurementType] = useState("goods");
  const [businessDomain, setBusinessDomain] = useState("general");
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [formOpen, setFormOpen] = useState(false);

  // Minimum suppliers implied by the package value (mirrors the rule pack:
  // ≤100tr = chỉ định (1); trên đó = chào giá/đấu thầu rộng rãi (3)). Validated
  // here so a package that can't clear CP1 is caught at intake, not mid-run.
  const requiredSuppliers = Number(value) > 0 && Number(value) <= 100_000_000 ? 1 : 3;
  const suppliersShort = Number(value) > 0 && suppliers.length < requiredSuppliers;

  const valid = useMemo(
    () =>
      Boolean(
        file &&
        title.trim() &&
        reference.trim() &&
        Number(value) > 0 &&
        Number(deadline) > 0 &&
        owner.trim() &&
        suppliers.length >= requiredSuppliers,
      ),
    [deadline, file, owner, reference, suppliers, title, value, requiredSuppliers],
  );

  const visibleCases = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("vi");
    return (cases ?? []).filter((item) => {
      const matchesType =
        typeFilter === "all" || item.procurement_type === typeFilter;
      const matchesQuery =
        !query ||
        item.title.toLocaleLowerCase("vi").includes(query) ||
        item.source_pr_ref.toLocaleLowerCase("vi").includes(query) ||
        item.owner_name.toLocaleLowerCase("vi").includes(query);
      return matchesType && matchesQuery;
    });
  }, [cases, search, typeFilter]);

  const refresh = useCallback(() => {
    apiClient()
      .listPreparationCases()
      .then((rows) => {
        setCases(rows);
        setError(null);
      })
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : "Lỗi không rõ"),
      );
  }, []);

  useEffect(() => refresh(), [refresh]);

  useEffect(() => {
    if (!formOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) setFormOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [busy, formOpen]);

  async function create() {
    if (!file || !valid) return;
    setBusy(true);
    setError(null);
    try {
      const { case_id } = await apiClient().uploadPreparationCase(file, {
        title: title.trim(),
        description: description.trim(),
        source_pr_ref: reference.trim(),
        estimated_value_minor: Number(value),
        deadline: `${deadline} ngày`,
        owner_name: owner.trim(),
        procurement_type: procurementType,
        business_domain: businessDomain,
        supplier_names: suppliers.join("\n"),
      });
      toast.success(
        "Đã lưu nguồn PR và gửi yêu cầu xác minh cho người phê duyệt.",
      );
      router.push(`/procurement/dw01/cases/${case_id}`);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Lỗi không rõ";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-[1320px] space-y-6">
      <PageHeading
        eyebrow="DW-THAU-01 · Chuẩn bị hồ sơ"
        icon={ShieldCheck}
        title="Quản lý gói thầu"
        description="Tiếp nhận PR đã duyệt, kiểm tra thông tin đầu vào và xây dựng hồ sơ mời thầu theo từng bước có người chịu trách nhiệm phê duyệt."
        actions={
          <>
            {!DW01_READONLY && (
              <Button variant="outline" asChild>
                <a href="/templates/dw01/01-approved-pr.md" download>
                  <FileText /> Tải mẫu PR
                </a>
              </Button>
            )}
            {canCreate && (
              <Button onClick={() => setFormOpen(true)}>
                <Upload /> Tạo hồ sơ
              </Button>
            )}
          </>
        }
      />

      {error && (
        <Alert variant="destructive">
          <p>{error}</p>
        </Alert>
      )}

      {DW01_READONLY && (
        <Alert>
          <p>
            💬 Hồ sơ mua sắm được tạo bằng cách <strong>nhắn tin cho Digital
            Worker trên Slack</strong> (vd: «Tôi muốn mua 100 laptop»). Trang
            web chỉ dùng để theo dõi tiến trình, tài liệu và audit.
          </p>
        </Alert>
      )}

      {canCreate && formOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6"
          role="dialog"
          aria-modal="true"
          aria-labelledby="new-case-title"
        >
          <button
            type="button"
            className="absolute inset-0 bg-[#071d33]/55 backdrop-blur-[2px]"
            aria-label="Đóng cửa sổ tạo hồ sơ"
            onClick={() => {
              if (!busy) setFormOpen(false);
            }}
          />
          <Card className="relative z-10 flex max-h-[94vh] w-full max-w-6xl flex-col overflow-hidden border-0 shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b bg-slate-50/90 px-5 py-4 sm:px-6">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 id="new-case-title" className="font-semibold">
                    Tạo hồ sơ từ PR đã duyệt
                  </h2>
                  <Badge variant="warning">Cần xác minh chéo</Badge>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  Mọi trường bắt buộc đều được lưu vào hệ thống; file gốc được
                  giữ nguyên để đối chiếu khi cần.
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0"
                onClick={() => setFormOpen(false)}
                disabled={busy}
                aria-label="Đóng"
              >
                <X />
              </Button>
            </div>
            <CardContent className="overflow-y-auto pt-6">
              {error && (
                <Alert variant="destructive" className="mb-5">
                  <p>{error}</p>
                </Alert>
              )}
              <div className="grid gap-8 xl:grid-cols-[minmax(300px,0.82fr)_minmax(0,1.55fr)]">
                <div className="space-y-6 xl:border-r xl:pr-8">
                  <div>
                    <p className="mb-2 text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                      1. Tài liệu nguồn
                    </p>
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      className="group flex min-h-40 w-full flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50/60 px-5 text-center transition-colors hover:border-primary/50 hover:bg-[#edf5fa]"
                    >
                      <span className="flex size-11 items-center justify-center rounded-2xl bg-white text-slate-600 shadow-sm group-hover:text-primary">
                        <Upload className="size-5" />
                      </span>
                      <span className="mt-3 text-sm font-semibold">
                        {file ? file.name : "Chọn file PR đã duyệt"}
                      </span>
                      <span className="mt-1 text-xs text-muted-foreground">
                        UTF-8 .txt hoặc .md · tối đa 5 MiB
                      </span>
                    </button>
                    <input
                      ref={fileInputRef}
                      className="sr-only"
                      type="file"
                      accept=".txt,.md,text/plain,text/markdown"
                      onChange={(event) =>
                        setFile(event.target.files?.[0] ?? null)
                      }
                    />
                  </div>

                  <div>
                    <p className="mb-2 text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                      2. Phân loại
                    </p>
                    <div className="space-y-3">
                      <FieldLabel label="Loại gói thầu" required>
                        <Select
                          value={procurementType}
                          onChange={(event) =>
                            setProcurementType(event.target.value)
                          }
                        >
                          {PROCUREMENT_TYPES.map((item) => (
                            <option key={item.value} value={item.value}>
                              {item.label}
                            </option>
                          ))}
                        </Select>
                      </FieldLabel>
                      <FieldLabel label="Lĩnh vực nghiệp vụ" required>
                        <Select
                          value={businessDomain}
                          onChange={(event) =>
                            setBusinessDomain(event.target.value)
                          }
                        >
                          {BUSINESS_DOMAINS.map((item) => (
                            <option key={item.value} value={item.value}>
                              {item.label}
                            </option>
                          ))}
                        </Select>
                      </FieldLabel>
                    </div>
                  </div>
                </div>

                <div className="min-w-0">
                  <p className="mb-3 text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                    3. Thông tin hồ sơ
                  </p>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <FieldLabel
                      label="Tên gói thầu"
                      required
                      className="sm:col-span-2"
                    >
                      <Input
                        value={title}
                        onChange={(event) => setTitle(event.target.value)}
                        placeholder="Ví dụ: Cung cấp thiết bị CNTT năm 2026"
                      />
                    </FieldLabel>
                    <FieldLabel label="Mã/tham chiếu PR" required>
                      <Input
                        value={reference}
                        onChange={(event) => setReference(event.target.value)}
                        placeholder="PR-2026-..."
                      />
                    </FieldLabel>
                    <FieldLabel label="Chủ sở hữu nghiệp vụ" required>
                      <Input
                        value={owner}
                        onChange={(event) => setOwner(event.target.value)}
                        placeholder="Họ tên người chịu trách nhiệm"
                      />
                    </FieldLabel>
                    <FieldLabel label="Giá trị dự toán (VND)" required>
                      <Input
                        inputMode="numeric"
                        value={formatThousands(value)}
                        onChange={(event) =>
                          setValue(event.target.value.replace(/\D/g, ""))
                        }
                        placeholder="Ví dụ: 2.500.000.000"
                      />
                      {value && (
                        <p className="mt-1 text-xs text-muted-foreground">
                          ≈ {vndInWords(value)}
                        </p>
                      )}
                    </FieldLabel>
                    <FieldLabel label="Thời hạn thực hiện (số ngày)" required>
                      <div className="relative">
                        <Input
                          inputMode="numeric"
                          value={deadline}
                          onChange={(event) =>
                            setDeadline(event.target.value.replace(/\D/g, ""))
                          }
                          placeholder="Ví dụ: 45"
                          className="pr-12"
                        />
                        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
                          ngày
                        </span>
                      </div>
                    </FieldLabel>
                    <FieldLabel
                      label="Mô tả ngắn"
                      hint="Không bắt buộc"
                      className="sm:col-span-2"
                    >
                      <Textarea
                        rows={3}
                        value={description}
                        onChange={(event) => setDescription(event.target.value)}
                        placeholder="Mục tiêu và phạm vi chính của gói thầu"
                      />
                    </FieldLabel>
                    <div className="min-w-0 sm:col-span-2">
                      <label
                        htmlFor="supplier-name"
                        className="mb-1.5 block text-sm font-medium"
                      >
                        Nhà cung cấp dự kiến{" "}
                        <span className="text-destructive">*</span>
                      </label>
                      <TagInput
                        id="supplier-name"
                        values={suppliers}
                        onChange={setSuppliers}
                        placeholder="Nhập tên nhà cung cấp"
                        helpText="Nhấn Enter hoặc nút Thêm sau mỗi nhà cung cấp. Gói > 100 triệu (chào giá cạnh tranh / đấu thầu rộng rãi) cần tối thiểu 3 nhà cung cấp."
                      />
                      {suppliersShort && (
                        <p className="mt-1 text-xs font-medium text-destructive">
                          Gói {formatThousands(value)} VND cần tối thiểu{" "}
                          {requiredSuppliers} nhà cung cấp (đang có{" "}
                          {suppliers.length}) — chưa đủ để nộp.
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="mt-6 flex flex-col gap-4 rounded-xl border border-[#cddfeb] bg-[#eef5fa] p-4 sm:flex-row sm:items-center sm:justify-between">
                    <p className="max-w-xl text-xs leading-5 text-slate-600">
                      Sau khi tạo, Bình sẽ nhận thông báo riêng trên Slack để
                      xác minh hồ sơ. Người lập không thể tự xác minh hồ sơ của
                      mình.
                    </p>
                    <Button
                      className="shrink-0"
                      onClick={() => void create()}
                      disabled={!valid || busy}
                    >
                      <Upload />
                      {busy ? "Đang tải lên…" : "Tạo và gửi xác minh"}
                    </Button>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      <section className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold">Danh sách hồ sơ</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Tìm kiếm, lọc và mở hồ sơ cần xử lý.
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground" />
              <Input
                className="pl-9 sm:w-64"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Tên, mã PR, người phụ trách…"
              />
            </div>
            <div className="relative">
              <Filter className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground" />
              <Select
                className="pl-9 pr-8 sm:w-48"
                value={typeFilter}
                onChange={(event) => setTypeFilter(event.target.value)}
              >
                <option value="all">Tất cả loại gói</option>
                {PROCUREMENT_TYPES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.shortLabel}
                  </option>
                ))}
              </Select>
            </div>
          </div>
        </div>

        {cases === null && !error && <Skeleton className="h-56 rounded-2xl" />}
        {cases !== null && visibleCases.length === 0 && (
          <EmptyState
            icon={FolderKanban}
            title={cases.length === 0 ? "Chưa có hồ sơ" : "Không có kết quả"}
            description={
              cases.length === 0
                ? "Tạo hồ sơ đầu tiên từ PR đã được phê duyệt."
                : "Thử thay đổi từ khóa hoặc bộ lọc loại gói thầu."
            }
          />
        )}
        {visibleCases.length > 0 && (
          <Card className="overflow-hidden">
            <div className="divide-y">
              {visibleCases.map((item) => {
                const state = STATE_BADGE(item.state);
                return (
                  <Link
                    key={item.id}
                    href={`/procurement/dw01/cases/${item.id}`}
                    className="group grid gap-3 px-5 py-4 transition-colors hover:bg-slate-50 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:px-6"
                  >
                    <div className="flex min-w-0 items-start gap-3">
                      <span className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-600 group-hover:bg-primary group-hover:text-white">
                        <FileText className="size-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold group-hover:text-primary">
                          {item.title}
                        </span>
                        <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                          <span>{item.source_pr_ref}</span>
                          <span>·</span>
                          <span>{formatVnd(item.estimated_value_minor)}</span>
                          <span>·</span>
                          <span>{item.owner_name}</span>
                        </span>
                        <span className="mt-2 flex flex-wrap gap-1.5">
                          <Badge variant="secondary">
                            {procurementTypeLabel(item.procurement_type)}
                          </Badge>
                          <Badge variant="outline">
                            {businessDomainLabel(item.business_domain)}
                          </Badge>
                        </span>
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3 sm:justify-end">
                      <Badge variant={state.variant}>{state.label}</Badge>
                      <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-1" />
                    </div>
                  </Link>
                );
              })}
            </div>
          </Card>
        )}
      </section>
    </div>
  );
}

function FieldLabel({
  label,
  hint,
  required = false,
  className = "",
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={className}>
      <span className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
        {label}
        {required && <span className="text-destructive">*</span>}
        {hint && (
          <span className="text-xs font-normal text-muted-foreground">
            · {hint}
          </span>
        )}
      </span>
      {children}
    </label>
  );
}
