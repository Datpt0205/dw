"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowRight,
  BadgeCheck,
  FileSearch,
  PauseCircle,
  Play,
  RefreshCw,
  Trophy,
} from "lucide-react";
import { toast } from "sonner";
import type { Run, TenderCase } from "@dw/contracts";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@dw/ui";
import { apiClient } from "../../../../lib/session";

const CASE_STATUS: Record<
  string,
  { label: string; variant: "secondary" | "warning" | "success" }
> = {
  draft: { label: "nháp", variant: "secondary" },
  analyzing: { label: "đang phân tích", variant: "warning" },
  recommendation_ready: { label: "chờ phê duyệt", variant: "warning" },
  completed: { label: "hoàn tất", variant: "success" },
};

const FINDING_STATUS: Record<string, { label: string; className: string }> = {
  compliant: { label: "đạt", className: "text-success" },
  non_compliant: { label: "không đạt", className: "text-destructive" },
  partial: { label: "một phần", className: "text-warning" },
  missing_evidence: { label: "thiếu bằng chứng", className: "text-warning" },
};

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
      setRun(
        loaded.last_run_id ? await client.getRun(loaded.last_run_id) : null,
      );
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    }
  }, [caseId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function analyze() {
    setBusy(true);
    try {
      await apiClient().analyzeTenderCase(caseId);
      toast.success("Phân tích xong — đề xuất đang chờ phê duyệt");
      await refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setBusy(false);
    }
  }

  if (!tenderCase) {
    return (
      <div className="mx-auto max-w-5xl space-y-4">
        {error ? (
          <Alert variant="destructive">
            <AlertTitle>Không tải được hồ sơ</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : (
          <>
            <Skeleton className="h-8 w-1/2" />
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-64 w-full" />
          </>
        )}
      </div>
    );
  }

  const status = CASE_STATUS[tenderCase.status] ?? {
    label: tenderCase.status,
    variant: "secondary" as const,
  };
  const suppliers = Array.from(
    new Set(tenderCase.findings.map((f) => f.supplier_name)),
  ).sort();
  const rec = tenderCase.recommendation;
  const notAnalyzed = tenderCase.requirements.length === 0;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <FileSearch className="size-6 text-muted-foreground" />
            {tenderCase.title}
          </h1>
          <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
            <Badge variant={status.variant}>{status.label}</Badge>
            {tenderCase.export_ref && (
              <code className="text-xs">{tenderCase.export_ref}</code>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={() => void analyze()}
            disabled={busy || tenderCase.status === "analyzing"}
          >
            <Play />
            {busy ? "Đang phân tích…" : "Phân tích hồ sơ"}
          </Button>
          <Button variant="outline" size="icon" onClick={() => void refresh()}>
            <RefreshCw />
          </Button>
        </div>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}

      {notAnalyzed && (
        <Alert variant="info">
          <FileSearch className="size-4" />
          <AlertTitle>Hồ sơ đã sẵn sàng</AlertTitle>
          <AlertDescription>
            Bấm <strong>Phân tích hồ sơ</strong> — máy sẽ trích yêu cầu từ RFQ,
            đối chiếu từng nhà cung cấp kèm trích dẫn và chấm điểm.
          </AlertDescription>
        </Alert>
      )}

      {run?.status === "waiting_approval" && (
        <Alert variant="warning">
          <PauseCircle className="size-4" />
          <AlertTitle>Đang chờ phê duyệt</AlertTitle>
          <AlertDescription className="flex items-center justify-between gap-3">
            Đề xuất đã sẵn sàng — cần người có quyền duyệt quyết định.
            <Button size="sm" variant="outline" asChild>
              <Link href="/approvals">
                Mở Phê duyệt <ArrowRight />
              </Link>
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {run?.status === "completed" && (
        <Alert variant="success">
          <BadgeCheck className="size-4" />
          <AlertTitle>Đã phê duyệt và hoàn tất</AlertTitle>
          <AlertDescription>
            Evaluation pack đã xuất vào kho tài liệu (MinIO); toàn bộ quá trình
            có trong Nhật ký.
          </AlertDescription>
        </Alert>
      )}

      {rec && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Trophy className="size-4 text-warning" />
              Khuyến nghị:{" "}
              <span className="text-success">
                {rec.recommended_supplier ??
                  "không có nhà cung cấp đủ điều kiện"}
              </span>
              {rec.gate_passed ? (
                <Badge variant="success">gate passed</Badge>
              ) : (
                <Badge variant="warning">gate violations</Badge>
              )}
            </CardTitle>
            <CardDescription>{rec.rationale}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nhà cung cấp</TableHead>
                  <TableHead>Tổng điểm</TableHead>
                  <TableHead>Mandatory</TableHead>
                  <TableHead>Kết quả</TableHead>
                  <TableHead>Vi phạm</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rec.supplier_scores.map((score) => (
                  <TableRow key={score.supplier_name}>
                    <TableCell className="font-medium">
                      {score.supplier_name}
                    </TableCell>
                    <TableCell className="font-mono text-base">
                      {score.total_score}
                    </TableCell>
                    <TableCell>
                      {score.mandatory_passed ? (
                        <Badge variant="success">đạt</Badge>
                      ) : (
                        <Badge variant="destructive">không đạt</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {score.eligible ? (
                        <Badge variant="success">đủ điều kiện</Badge>
                      ) : (
                        <Badge variant="destructive">bị loại</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-warning">
                      {score.violations.join(", ") || "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <p className="text-xs text-muted-foreground">
              Chính sách chấm điểm v{rec.scoring_policy_version} ·{" "}
              {rec.evidence_count} bằng chứng · độ tin cậy{" "}
              {(rec.confidence * 100).toFixed(0)}% — điểm số do engine
              deterministic quyết định, không phải model.
            </p>
          </CardContent>
        </Card>
      )}

      {tenderCase.requirements.length > 0 && (
        <Tabs defaultValue="matrix">
          <TabsList>
            <TabsTrigger value="matrix">
              Ma trận tuân thủ ({tenderCase.requirements.length} ×{" "}
              {suppliers.length})
            </TabsTrigger>
            <TabsTrigger value="requirements">Yêu cầu</TabsTrigger>
          </TabsList>

          <TabsContent value="matrix">
            <Card>
              <CardContent className="pt-5">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Yêu cầu</TableHead>
                      {suppliers.map((supplier) => (
                        <TableHead key={supplier}>{supplier}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tenderCase.requirements.map((requirement) => (
                      <TableRow key={requirement.code} className="align-top">
                        <TableCell className="min-w-48">
                          <span className="font-medium">
                            {requirement.code}
                          </span>{" "}
                          <Badge variant="outline">
                            {requirement.kind === "mandatory"
                              ? "bắt buộc"
                              : requirement.kind === "weighted"
                                ? `trọng số ${requirement.weight}`
                                : requirement.kind}
                          </Badge>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {requirement.statement}
                          </p>
                        </TableCell>
                        {suppliers.map((supplier) => {
                          const finding = tenderCase.findings.find(
                            (f) =>
                              f.requirement_code === requirement.code &&
                              f.supplier_name === supplier,
                          );
                          if (!finding)
                            return <TableCell key={supplier}>—</TableCell>;
                          const fs = FINDING_STATUS[finding.status] ?? {
                            label: finding.status,
                            className: "",
                          };
                          return (
                            <TableCell key={supplier}>
                              <span className={`font-medium ${fs.className}`}>
                                {fs.label} ({finding.raw_score})
                              </span>
                              {finding.quote && (
                                <p className="mt-1 border-l-2 border-border pl-2 text-xs italic text-muted-foreground">
                                  “{finding.quote}”
                                </p>
                              )}
                            </TableCell>
                          );
                        })}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="requirements">
            <Card>
              <CardContent className="pt-5">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Mã</TableHead>
                      <TableHead>Nội dung</TableHead>
                      <TableHead>Loại</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tenderCase.requirements.map((requirement) => (
                      <TableRow key={requirement.code}>
                        <TableCell className="font-mono">
                          {requirement.code}
                        </TableCell>
                        <TableCell>{requirement.statement}</TableCell>
                        <TableCell>
                          <Badge variant="outline">
                            {requirement.kind === "mandatory"
                              ? "bắt buộc"
                              : `trọng số ${requirement.weight}`}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
