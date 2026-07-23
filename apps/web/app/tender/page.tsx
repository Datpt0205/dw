"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, Plus, Zap } from "lucide-react";
import { toast } from "sonner";
import type { TenderCase } from "@dw/contracts";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Skeleton,
  Textarea,
} from "@dw/ui";
import { apiClient, canCreate, loadSession } from "../../lib/session";

const STATUS: Record<
  string,
  { label: string; variant: "secondary" | "warning" | "success" }
> = {
  draft: { label: "nháp", variant: "secondary" },
  analyzing: { label: "đang phân tích", variant: "warning" },
  recommendation_ready: { label: "chờ phê duyệt", variant: "warning" },
  completed: { label: "hoàn tất", variant: "success" },
};

export default function TenderCasesPage() {
  const router = useRouter();
  const [cases, setCases] = useState<TenderCase[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [rfq, setRfq] = useState("");
  const [supplierAName, setSupplierAName] = useState("");
  const [supplierA, setSupplierA] = useState("");
  const [supplierBName, setSupplierBName] = useState("");
  const [supplierB, setSupplierB] = useState("");

  const allowed = canCreate(loadSession());

  const refresh = useCallback(() => {
    apiClient()
      .listTenderCases()
      .then(setCases)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "lỗi không rõ"),
      );
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function createDemo() {
    setBusy(true);
    try {
      const { case_id } = await apiClient().createDemoTenderCase();
      toast.success("Đã tạo hồ sơ mẫu");
      router.push(`/tender/cases/${case_id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "lỗi không rõ");
      setBusy(false);
    }
  }

  async function create() {
    setBusy(true);
    try {
      const documents: Parameters<
        ReturnType<typeof apiClient>["createTenderCase"]
      >[0]["documents"] = [{ kind: "rfq", title: "RFQ", content: rfq }];
      if (supplierAName.trim() && supplierA.trim()) {
        documents.push({
          kind: "supplier_submission",
          title: `Chào giá ${supplierAName}`,
          content: supplierA,
          supplier_name: supplierAName,
        });
      }
      if (supplierBName.trim() && supplierB.trim()) {
        documents.push({
          kind: "supplier_submission",
          title: `Chào giá ${supplierBName}`,
          content: supplierB,
          supplier_name: supplierBName,
        });
      }
      const { case_id } = await apiClient().createTenderCase({
        title,
        documents,
      });
      router.push(`/tender/cases/${case_id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "lỗi không rõ");
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Hồ sơ thầu</h1>
          <p className="text-sm text-muted-foreground">
            Mỗi hồ sơ gồm 1 RFQ và các bản chào giá của nhà cung cấp.
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => void createDemo()} disabled={busy || !allowed}>
            <Zap />
            {busy ? "Đang tạo…" : "Tạo hồ sơ mẫu"}
          </Button>
          <Button
            variant="outline"
            onClick={() => setShowForm((v) => !v)}
            disabled={!allowed}
          >
            <Plus /> Tự nhập
          </Button>
        </div>
      </div>
      {!allowed && (
        <p className="rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
          Vai «Người phê duyệt» chỉ duyệt, không tạo hồ sơ — sang Đăng nhập chọn
          <strong> Nguyễn Văn An (Nhân viên)</strong> để tạo.
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}

      {showForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Tạo hồ sơ mới</CardTitle>
            <CardDescription>
              Dán nội dung RFQ và tối thiểu một bản chào giá.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input
              placeholder="Tiêu đề hồ sơ (VD: RFQ vật tư Q3)"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <Textarea
              className="font-mono text-xs"
              rows={5}
              placeholder="Nội dung RFQ…"
              value={rfq}
              onChange={(e) => setRfq(e.target.value)}
            />
            <div className="grid gap-3 md:grid-cols-2">
              {[
                {
                  name: supplierAName,
                  setName: setSupplierAName,
                  content: supplierA,
                  setContent: setSupplierA,
                  label: "Nhà cung cấp 1",
                },
                {
                  name: supplierBName,
                  setName: setSupplierBName,
                  content: supplierB,
                  setContent: setSupplierB,
                  label: "Nhà cung cấp 2 (tuỳ chọn)",
                },
              ].map((supplier) => (
                <div key={supplier.label} className="space-y-2">
                  <Input
                    placeholder={`Tên ${supplier.label}`}
                    value={supplier.name}
                    onChange={(e) => supplier.setName(e.target.value)}
                  />
                  <Textarea
                    className="font-mono text-xs"
                    rows={5}
                    placeholder="Hồ sơ chào giá…"
                    value={supplier.content}
                    onChange={(e) => supplier.setContent(e.target.value)}
                  />
                </div>
              ))}
            </div>
            <Button
              onClick={create}
              disabled={
                busy ||
                !title.trim() ||
                !rfq.trim() ||
                !supplierAName.trim() ||
                !supplierA.trim()
              }
            >
              {busy ? "Đang tạo…" : "Tạo hồ sơ"}
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="space-y-2">
        {cases === null && !error && <Skeleton className="h-32 w-full" />}
        {cases?.length === 0 && (
          <Card>
            <CardContent className="pt-5 text-sm text-muted-foreground">
              Chưa có hồ sơ nào — bấm <strong>Tạo hồ sơ mẫu</strong> để bắt đầu.
            </CardContent>
          </Card>
        )}
        {cases?.map((tenderCase) => {
          const status = STATUS[tenderCase.status] ?? {
            label: tenderCase.status,
            variant: "secondary" as const,
          };
          return (
            <Link
              key={tenderCase.id}
              href={`/tender/cases/${tenderCase.id}`}
              className="group flex items-center justify-between rounded-xl border bg-card p-4 shadow-sm transition-colors hover:bg-accent"
            >
              <span className="font-medium">{tenderCase.title}</span>
              <span className="flex items-center gap-2">
                <Badge variant={status.variant}>{status.label}</Badge>
                <ChevronRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
              </span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
