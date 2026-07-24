"use client";
/* eslint-disable @typescript-eslint/no-explicit-any -- artifact content is dynamic JSON */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  CheckCircle2,
  Circle,
  Download,
  Hourglass,
  Play,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import type { PreparationArtifact, PreparationCase, Run } from "@dw/api-client";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  cn,
} from "@dw/ui";
import { useAuth } from "../../../../../lib/auth/auth-context";
import { apiClient } from "../../../../../lib/session";
import { STATE_BADGE, STEPPER, currentStepIndex, formatVnd } from "../../state";

const ARTIFACT_TITLE: Record<string, string> = {
  demand_snapshot: "Chuẩn hoá nhu cầu",
  completeness_report: "Kiểm tra đầy đủ",
  clarification_list: "Danh sách làm rõ",
  procurement_approach: "Phương án mua sắm (CP1)",
  solicitation_package: "Bộ hồ sơ RFQ/HSMT",
  evaluation_criteria: "Tiêu chí đánh giá",
  supplier_shortlist: "Danh sách nhà cung cấp mời",
  risk_compliance_check: "Kiểm tra rủi ro",
  official_package_manifest: "Bản chính thức + manifest",
};

const ARTIFACT_ORDER = Object.keys(ARTIFACT_TITLE);

function download(filename: string, text: string, type: string) {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function Dw01CaseDetail({
  params,
}: {
  params: Promise<{ caseId: string }>;
}) {
  const { caseId } = use(params);
  const { hasScope } = useAuth();
  const canRun = hasScope("tender.write");
  const [data, setData] = useState<PreparationCase | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const loaded = await apiClient().getPreparationCase(caseId);
      setData(loaded);
      if (loaded.last_run_id) setRun(await apiClient().getRun(loaded.last_run_id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    }
  }, [caseId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function runDw01() {
    setBusy(true);
    setError(null);
    try {
      await apiClient().runPreparation(caseId);
      toast.success("DW01 đã chạy — dừng tại CP1 chờ phê duyệt.");
      await refresh();
    } catch (e) {
      const m = e instanceof Error ? e.message : "lỗi không rõ";
      setError(m);
      toast.error(m);
    } finally {
      setBusy(false);
    }
  }

  if (!data) {
    return (
      <p className="text-sm text-muted-foreground">
        {error ?? "Đang tải…"}
      </p>
    );
  }

  const badge = STATE_BADGE(data.state);
  const stepIdx = currentStepIndex(data.state);
  const artifacts = [...data.artifacts].sort(
    (a, b) =>
      ARTIFACT_ORDER.indexOf(a.artifact_type) -
      ARTIFACT_ORDER.indexOf(b.artifact_type),
  );
  const official = artifacts.find(
    (a) => a.artifact_type === "official_package_manifest",
  );
  const waiting = run?.status === "waiting_approval";
  const runnable = data.state === "intake_ready" && canRun;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            href="/procurement/dw01"
            className="text-xs text-muted-foreground hover:underline"
          >
            ← Danh sách hồ sơ
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">
            {data.title}
          </h1>
          <p className="text-sm text-muted-foreground">
            {formatVnd(data.estimated_value_minor)}
            {data.method_key ? ` · ${data.method_key}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={badge.variant}>{badge.label}</Badge>
          <Button variant="ghost" size="icon" title="Làm mới" onClick={refresh}>
            <RefreshCw />
          </Button>
        </div>
      </div>

      {/* Stepper */}
      <Card>
        <CardContent className="flex flex-wrap gap-2 pt-5">
          {STEPPER.map((s, i) => (
            <div key={s.key} className="flex items-center gap-2">
              <span
                className={cn(
                  "flex items-center gap-1.5 rounded-full px-3 py-1 text-xs",
                  i < stepIdx
                    ? "bg-success/15 text-success"
                    : i === stepIdx
                      ? "bg-primary/15 font-medium text-primary"
                      : "bg-muted text-muted-foreground",
                )}
              >
                {i < stepIdx ? (
                  <CheckCircle2 className="size-3.5" />
                ) : (
                  <Circle className="size-3.5" />
                )}
                {s.label}
              </span>
            </div>
          ))}
        </CardContent>
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {runnable && (
        <Card className="border-primary/40">
          <CardContent className="flex items-center justify-between gap-3 pt-5 text-sm">
            <span>Hồ sơ đã sẵn sàng. Chạy DW01 để tạo phương án và dừng ở CP1.</span>
            <Button onClick={() => void runDw01()} disabled={busy}>
              <Play /> {busy ? "Đang chạy…" : "Chạy DW01"}
            </Button>
          </CardContent>
        </Card>
      )}

      {waiting && (
        <Alert>
          <Hourglass className="size-4" />
          <div className="text-sm">
            Đang dừng chờ phê duyệt tại checkpoint.{" "}
            <Link className="underline" href="/approvals">
              Vào trang Phê duyệt
            </Link>{" "}
            (cần vai Người phê duyệt), duyệt xong quay lại bấm{" "}
            <strong>Làm mới</strong>.
          </div>
        </Alert>
      )}

      {official && (
        <Card className="border-success/40">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base text-success">
              <CheckCircle2 className="size-4" /> Bộ hồ sơ chính thức đã khoá
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                download(
                  `official-manifest-${caseId}.json`,
                  JSON.stringify(official.content, null, 2),
                  "application/json",
                )
              }
            >
              <Download /> Tải manifest JSON
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                download(
                  `solicitation-package-${caseId}.md`,
                  String(official.content["package_markdown"] ?? ""),
                  "text/markdown",
                )
              }
            >
              <Download /> Tải bộ hồ sơ (.md)
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Artifacts */}
      <div className="space-y-3">
        {artifacts.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Chưa có kết quả — bấm «Chạy DW01».
          </p>
        )}
        {artifacts.map((a) => (
          <ArtifactCard key={a.id} artifact={a} />
        ))}
      </div>
    </div>
  );
}

function ArtifactCard({ artifact }: { artifact: PreparationArtifact }) {
  const c = artifact.content as Record<string, any>;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-sm">
          <span>{ARTIFACT_TITLE[artifact.artifact_type] ?? artifact.artifact_type}</span>
          <Badge variant="secondary">v{artifact.artifact_version}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5 text-sm">
        {renderArtifact(artifact.artifact_type, c)}
      </CardContent>
    </Card>
  );
}

function renderArtifact(type: string, c: Record<string, any>) {
  switch (type) {
    case "procurement_approach":
      return (
        <>
          <Row k="Hình thức" v={c.method?.label} />
          <Row k="Số NCC mời" v={`${c.supplier_count_planned} (tối thiểu ${c.min_suppliers})`} />
          <Row k="Chiến lược" v={c.sourcing_strategy} />
          <Row k="Pháp chế/Tài chính" v={`${c.legal_review_required ? "Cần pháp chế" : "—"} · ${c.finance_review_required ? "Cần tài chính" : "—"}`} />
          <p className="text-xs text-muted-foreground">{c.rationale}</p>
        </>
      );
    case "clarification_list":
      return (c.items ?? []).length === 0 ? (
        <p className="text-muted-foreground">Không có điểm cần làm rõ.</p>
      ) : (
        <ul className="list-disc space-y-0.5 pl-5">
          {(c.items ?? []).map((it: any) => (
            <li key={it.id}>
              {it.question}
              {it.blocking && <Badge variant="warning" className="ml-2">blocking</Badge>}
            </li>
          ))}
        </ul>
      );
    case "completeness_report":
      return (
        <>
          <Row k="Đầy đủ" v={c.complete ? "Có" : "Không"} />
          <Row k="Điểm chưa rõ" v={String(c.unknown_count)} />
          <p className="text-xs text-muted-foreground">{c.note}</p>
        </>
      );
    case "evaluation_criteria":
      return (
        <>
          <p className="text-xs text-muted-foreground">
            Tổng trọng số: {c.weighted_total}
          </p>
          <ul className="list-disc space-y-0.5 pl-5">
            {(c.weighted ?? []).map((w: any) => (
              <li key={w.code}>
                [{w.weight}%] {w.text}
              </li>
            ))}
            {(c.mandatory ?? []).map((m: any) => (
              <li key={m.code} className="text-muted-foreground">
                (pass/fail) {m.text}
              </li>
            ))}
          </ul>
        </>
      );
    case "supplier_shortlist":
      return (
        <>
          <ul className="list-disc space-y-0.5 pl-5">
            {(c.shortlist ?? []).map((s: any) => (
              <li key={s.name}>
                {s.name}
                {s.on_site_warranty && (
                  <Badge variant="success" className="ml-2">bảo hành tại chỗ</Badge>
                )}
              </li>
            ))}
          </ul>
          {(c.excluded ?? []).length > 0 && (
            <p className="text-xs text-muted-foreground">
              Loại: {(c.excluded ?? []).map((e: any) => e.name).join(", ")}
            </p>
          )}
        </>
      );
    case "risk_compliance_check":
      return (
        <ul className="space-y-0.5">
          {(c.checks ?? []).map((ck: any) => (
            <li key={ck.check} className="flex items-center gap-2">
              <Badge variant={ck.ok ? "success" : "destructive"}>
                {ck.ok ? "OK" : "!"}
              </Badge>
              {ck.check} — <span className="text-muted-foreground">{ck.detail}</span>
            </li>
          ))}
        </ul>
      );
    case "demand_snapshot":
      return (
        <>
          <Row k="Giá trị" v={c.estimated_value} />
          <Row k="Thời hạn" v={c.deadline} />
          <Row k="Số yêu cầu" v={String((c.requirement_lines ?? []).length)} />
        </>
      );
    case "solicitation_package":
      return (
        <>
          <Row k="Phạm vi" v={c.scope} />
          <p className="text-xs text-muted-foreground">
            Cấu trúc hồ sơ: {(c.response_structure ?? []).join(" · ")}
          </p>
        </>
      );
    case "official_package_manifest":
      return (
        <p className="text-xs text-muted-foreground">
          Rule pack v{c.rule_pack_version} · {(c.artifacts ?? []).length} artifact ·
          hash đã ghi. Tải bản chính thức ở khối phía trên.
        </p>
      );
    default:
      return (
        <pre className="overflow-x-auto rounded bg-muted/50 p-2 text-xs">
          {JSON.stringify(c, null, 2)}
        </pre>
      );
  }
}

function Row({ k, v }: { k: string; v: unknown }) {
  return (
    <div className="flex gap-2">
      <span className="w-32 shrink-0 text-muted-foreground">{k}</span>
      <span>{v == null ? "—" : String(v)}</span>
    </div>
  );
}
