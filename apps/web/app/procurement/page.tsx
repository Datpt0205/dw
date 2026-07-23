"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { TenderCase } from "@dw/contracts";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@dw/ui";
import { apiClient } from "../../lib/session";

export default function ProcurementPage() {
  const [cases, setCases] = useState<TenderCase[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [rfq, setRfq] = useState("");
  const [supplierAName, setSupplierAName] = useState("");
  const [supplierA, setSupplierA] = useState("");
  const [supplierBName, setSupplierBName] = useState("");
  const [supplierB, setSupplierB] = useState("");

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

  async function create() {
    setBusy(true);
    setError(null);
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
      window.location.href = `/procurement/cases/${case_id}`;
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setBusy(false);
    }
  }

  async function createDemo() {
    setBusy(true);
    setError(null);
    try {
      const { case_id } = await apiClient().createDemoTenderCase();
      window.location.href = `/procurement/cases/${case_id}`;
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Procurement — Tender cases</h1>
        <Button onClick={() => void createDemo()} disabled={busy}>
          {busy ? "Đang tạo…" : "⚡ Tạo hồ sơ mẫu"}
        </Button>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Tạo case mới</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <input
            className="w-full rounded-md border border-slate-300 p-2 text-sm dark:border-slate-700 dark:bg-slate-950"
            placeholder="Tiêu đề case (VD: RFQ vật tư Q3)"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <textarea
            className="w-full rounded-md border border-slate-300 p-2 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
            rows={5}
            placeholder="Nội dung RFQ…"
            value={rfq}
            onChange={(e) => setRfq(e.target.value)}
          />
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
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
                label: "Nhà cung cấp 2",
              },
            ].map((supplier) => (
              <div key={supplier.label} className="space-y-2">
                <input
                  className="w-full rounded-md border border-slate-300 p-2 text-sm dark:border-slate-700 dark:bg-slate-950"
                  placeholder={`Tên ${supplier.label}`}
                  value={supplier.name}
                  onChange={(e) => supplier.setName(e.target.value)}
                />
                <textarea
                  className="w-full rounded-md border border-slate-300 p-2 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
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
            {busy ? "Đang tạo…" : "Tạo tender case"}
          </Button>
        </CardContent>
      </Card>

      <div className="space-y-3">
        {cases === null && !error && <p className="text-sm">Đang tải…</p>}
        {cases?.length === 0 && <p className="text-sm">Chưa có case nào.</p>}
        {cases?.map((tenderCase) => (
          <Link
            key={tenderCase.id}
            href={`/procurement/cases/${tenderCase.id}`}
            className="block rounded-lg border border-slate-200 bg-white p-4 hover:border-slate-400 dark:border-slate-800 dark:bg-slate-900"
          >
            <div className="flex items-center justify-between">
              <span className="font-medium">{tenderCase.title}</span>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs dark:bg-slate-800">
                {tenderCase.status}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
