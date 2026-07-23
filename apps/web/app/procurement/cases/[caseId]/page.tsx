"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { Run, TenderCase } from "@dw/contracts";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@dw/ui";
import { apiClient } from "../../../../lib/session";

export default function TenderCaseDetailPage() {
  const params = useParams<{ caseId: string }>();
  const caseId = params.caseId;
  const [tenderCase, setTenderCase] = useState<TenderCase | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const client = apiClient();
      const loaded = await client.getTenderCase(caseId);
      setTenderCase(loaded);
      if (loaded.last_run_id) {
        setRun(await client.getRun(loaded.last_run_id));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    }
  }, [caseId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function analyze() {
    setBusy(true);
    setError(null);
    try {
      await apiClient().analyzeTenderCase(caseId);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setBusy(false);
    }
  }

  if (!tenderCase) {
    return <p className="text-sm">{error ?? "Đang tải…"}</p>;
  }

  const suppliers = Array.from(
    new Set(tenderCase.findings.map((f) => f.supplier_name)),
  ).sort();
  const rec = tenderCase.recommendation;

  return (
    <div className="max-w-6xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{tenderCase.title}</h1>
          <p className="text-xs text-slate-500">
            trạng thái: <strong>{tenderCase.status}</strong>
            {tenderCase.export_ref && (
              <>
                {" · pack: "}
                <code className="text-xs">{tenderCase.export_ref}</code>
              </>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={analyze}
            disabled={busy || tenderCase.status === "analyzing"}
          >
            {busy ? "Đang chạy…" : "Phân tích hồ sơ"}
          </Button>
          <Button variant="outline" onClick={() => void refresh()}>
            Làm mới
          </Button>
        </div>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}

      {run && run.status === "waiting_approval" && (
        <Card>
          <CardContent className="pt-4 text-sm">
            ⏸ Run <code className="text-xs">{run.id}</code> đang chờ phê duyệt —{" "}
            <Link className="text-blue-600 underline" href="/approvals">
              mở Approval inbox
            </Link>
          </CardContent>
        </Card>
      )}

      {rec && (
        <Card>
          <CardHeader>
            <CardTitle>
              Khuyến nghị:{" "}
              <span className="text-green-700 dark:text-green-400">
                {rec.recommended_supplier ??
                  "không có nhà cung cấp đủ điều kiện"}
              </span>{" "}
              {rec.gate_passed ? "✓ gate passed" : "⚠ gate violations"}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p>{rec.rationale}</p>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs uppercase text-slate-500">
                  <tr>
                    <th className="py-1 pr-3">Nhà cung cấp</th>
                    <th className="py-1 pr-3">Tổng điểm</th>
                    <th className="py-1 pr-3">Mandatory</th>
                    <th className="py-1 pr-3">Đủ điều kiện</th>
                    <th className="py-1">Vi phạm</th>
                  </tr>
                </thead>
                <tbody>
                  {rec.supplier_scores.map((score) => (
                    <tr
                      key={score.supplier_name}
                      className="border-t border-slate-200 dark:border-slate-800"
                    >
                      <td className="py-2 pr-3 font-medium">
                        {score.supplier_name}
                      </td>
                      <td className="py-2 pr-3 font-mono">
                        {score.total_score}
                      </td>
                      <td className="py-2 pr-3">
                        {score.mandatory_passed ? "✓" : "✗"}
                      </td>
                      <td className="py-2 pr-3">
                        {score.eligible ? "✓" : "✗ loại"}
                      </td>
                      <td className="py-2 text-xs text-amber-600">
                        {score.violations.join(", ") || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-slate-500">
              Chính sách chấm điểm v{rec.scoring_policy_version} ·{" "}
              {rec.evidence_count} bằng chứng · độ tin cậy{" "}
              {(rec.confidence * 100).toFixed(0)}%
            </p>
          </CardContent>
        </Card>
      )}

      {tenderCase.requirements.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>
              Ma trận tuân thủ ({tenderCase.requirements.length} yêu cầu ×{" "}
              {suppliers.length} nhà cung cấp)
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-1 pr-3">Yêu cầu</th>
                  <th className="py-1 pr-3">Loại</th>
                  {suppliers.map((supplier) => (
                    <th key={supplier} className="py-1 pr-3">
                      {supplier}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tenderCase.requirements.map((requirement) => (
                  <tr
                    key={requirement.code}
                    className="border-t border-slate-200 align-top dark:border-slate-800"
                  >
                    <td className="py-2 pr-3">
                      <strong>{requirement.code}</strong>
                      <p className="text-xs text-slate-500">
                        {requirement.statement}
                      </p>
                    </td>
                    <td className="py-2 pr-3 text-xs">
                      {requirement.kind}
                      {requirement.kind === "weighted" && (
                        <span className="block text-slate-500">
                          w={requirement.weight}
                        </span>
                      )}
                    </td>
                    {suppliers.map((supplier) => {
                      const finding = tenderCase.findings.find(
                        (f) =>
                          f.requirement_code === requirement.code &&
                          f.supplier_name === supplier,
                      );
                      if (!finding)
                        return (
                          <td key={supplier} className="py-2 pr-3">
                            —
                          </td>
                        );
                      const color =
                        finding.status === "compliant"
                          ? "text-green-700 dark:text-green-400"
                          : finding.status === "non_compliant"
                            ? "text-red-600"
                            : "text-amber-600";
                      return (
                        <td key={supplier} className="py-2 pr-3">
                          <span className={`font-medium ${color}`}>
                            {finding.status} ({finding.raw_score})
                          </span>
                          {finding.quote && (
                            <p className="text-xs italic text-slate-500">
                              “{finding.quote}”
                            </p>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
