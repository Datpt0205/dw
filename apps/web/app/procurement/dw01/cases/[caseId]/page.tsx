"use client";
/* eslint-disable @typescript-eslint/no-explicit-any -- artifact content is dynamic JSON */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  CheckCircle2,
  Circle,
  Download,
  FileCheck2,
  Hourglass,
  PackageCheck,
  Play,
  RefreshCw,
  Send,
  BellRing,
  Tags,
  XCircle,
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
  Input,
  Textarea,
  cn,
} from "@dw/ui";
import { useAuth } from "../../../../../lib/auth/auth-context";
import { apiClient } from "../../../../../lib/session";
import { TagInput } from "../../../../../components/tag-input";
import { businessDomainLabel, procurementTypeLabel } from "../../catalog";
import { STATE_BADGE, STEPPER, currentStepIndex, formatVnd } from "../../state";

const ARTIFACT_TITLE: Record<string, string> = {
  intake_verification: "Xác minh hồ sơ đầu vào",
  supplier_input: "Nguồn nhà cung cấp ứng viên",
  demand_snapshot: "Chuẩn hoá nhu cầu",
  completeness_report: "Kiểm tra đầy đủ",
  clarification_list: "Danh sách làm rõ",
  clarification_response: "Phản hồi làm rõ",
  procurement_approach: "Phương án mua sắm (CP1)",
  solicitation_package: "Bộ hồ sơ RFQ/HSMT",
  evaluation_criteria: "Tiêu chí đánh giá",
  supplier_shortlist: "Danh sách nhà cung cấp mời",
  risk_compliance_check: "Kiểm tra rủi ro",
  official_package_manifest: "Danh mục hồ sơ chính thức",
  publication_record: "Bằng chứng phát hành",
  addendum_draft: "Dự thảo văn bản sửa đổi (CP3)",
  addendum_decision: "Quyết định CP3",
  submission_register: "Sổ tiếp nhận hồ sơ dự thầu",
  bid_opening_record: "Biên bản và xác nhận mở thầu (CP4)",
  evaluation_handoff: "Gói bàn giao đánh giá",
};

const ARTIFACT_ORDER = Object.keys(ARTIFACT_TITLE);

const NOTIFICATION_LABELS: Record<string, string> = {
  "intake.approval_requested": "Đã gửi yêu cầu xác minh cho Bình",
  "intake.approval_escalated": "Đã gửi nhắc việc cho Chi",
  "intake.approved": "Đã thông báo hồ sơ được chấp thuận",
  "intake.rejected": "Đã thông báo hồ sơ bị từ chối",
};

const NOTIFICATION_STATUS: Record<string, string> = {
  queued: "Chờ gửi",
  processing: "Đang gửi",
  sent: "Đã gửi",
  failed: "Gửi thất bại",
  cancelled: "Đã huỷ",
};

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
  const [approvalReference, setApprovalReference] = useState("");
  const [verificationComment, setVerificationComment] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [answerSources, setAnswerSources] = useState<Record<string, string>>(
    {},
  );
  const [publicationFile, setPublicationFile] = useState<File | null>(null);
  const [publicationChannel, setPublicationChannel] = useState("Email công vụ");
  const [publicationRecipients, setPublicationRecipients] = useState("");
  const [publicationAt, setPublicationAt] = useState("");
  const [publicationReference, setPublicationReference] = useState("");
  const [submissionFile, setSubmissionFile] = useState<File | null>(null);
  const [submissionSupplier, setSubmissionSupplier] = useState("");
  const [submissionAt, setSubmissionAt] = useState("");
  const [submissionStatus, setSubmissionStatus] = useState<
    "on_time" | "late" | "replacement"
  >("on_time");
  const [submissionReference, setSubmissionReference] = useState("");
  const [addendumFile, setAddendumFile] = useState<File | null>(null);
  const [addendumChange, setAddendumChange] = useState("");
  const [addendumImpact, setAddendumImpact] = useState("");
  const [cp3Reference, setCp3Reference] = useState("");
  const [cp3Comment, setCp3Comment] = useState("");
  const [cp4File, setCp4File] = useState<File | null>(null);
  const [cp4At, setCp4At] = useState("");
  const [cp4Witnesses, setCp4Witnesses] = useState("");
  const [cp4Reference, setCp4Reference] = useState("");

  const refresh = useCallback(async () => {
    try {
      const loaded = await apiClient().getPreparationCase(caseId);
      setData(loaded);
      if (loaded.last_run_id)
        setRun(await apiClient().getRun(loaded.last_run_id));
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

  async function verifyIntake() {
    setBusy(true);
    setError(null);
    try {
      await apiClient().verifyPreparationIntake(caseId, {
        approval_reference: approvalReference,
        comment: verificationComment,
      });
      toast.success("Đã xác minh intake. Người lập có thể chạy DW01.");
      await refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Lỗi không rõ";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function rejectIntake() {
    setBusy(true);
    setError(null);
    try {
      await apiClient().rejectPreparationIntake(caseId, {
        comment: verificationComment,
      });
      toast.success(
        "Đã từ chối intake và xếp hàng thông báo Slack cho người tạo.",
      );
      await refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Lỗi không rõ";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function submitClarifications(items: any[]) {
    setBusy(true);
    setError(null);
    try {
      await apiClient().answerPreparationClarifications(
        caseId,
        items.map((item) => ({
          clarification_id: String(item.id),
          question: String(item.question),
          answer: answers[String(item.id)] ?? "",
          source_note: answerSources[String(item.id)] ?? "",
        })),
      );
      toast.success(
        "Đã lưu phản hồi. Hãy chạy lại DW01 để đánh giá trên dữ liệu mới.",
      );
      await refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Lỗi không rõ";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function recordPublication() {
    if (!publicationFile) return;
    setBusy(true);
    try {
      await apiClient().recordPreparationPublication(caseId, publicationFile, {
        channel: publicationChannel,
        recipient_summary: publicationRecipients,
        published_at: publicationAt,
        external_reference: publicationReference,
      });
      toast.success("Đã ghi nhận phát hành và lưu bằng chứng đối chiếu.");
      await refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Lỗi không rõ";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function recordSubmission() {
    if (!submissionFile) return;
    setBusy(true);
    try {
      await apiClient().recordPreparationSubmission(caseId, submissionFile, {
        supplier_name: submissionSupplier,
        received_at: submissionAt,
        receipt_status: submissionStatus,
        external_reference: submissionReference,
      });
      toast.success(
        "Đã lưu nguyên bản hồ sơ dự thầu và cập nhật sổ tiếp nhận.",
      );
      setSubmissionFile(null);
      setSubmissionSupplier("");
      setSubmissionReference("");
      await refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Lỗi không rõ";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function submitAddendum() {
    if (!addendumFile) return;
    setBusy(true);
    try {
      await apiClient().submitPreparationAddendum(caseId, addendumFile, {
        change_summary: addendumChange,
        impact_summary: addendumImpact,
      });
      toast.success("Đã trình addendum; case dừng chờ CP3.");
      await refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Lỗi không rõ";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function decideCp3(approve: boolean) {
    setBusy(true);
    try {
      await apiClient().decidePreparationCp3(caseId, {
        approve,
        approval_reference: cp3Reference,
        comment: cp3Comment,
      });
      toast.success(approve ? "Đã duyệt CP3." : "Đã từ chối addendum.");
      await refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Lỗi không rõ";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function completeCp4() {
    if (!cp4File) return;
    setBusy(true);
    try {
      await apiClient().completePreparationCp4(caseId, cp4File, {
        opening_at: cp4At,
        witnesses: cp4Witnesses,
        approval_reference: cp4Reference,
      });
      toast.success("CP4 đã được xác nhận; gói bàn giao đánh giá đã tạo.");
      await refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Lỗi không rõ";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  if (!data) {
    return (
      <p className="text-sm text-muted-foreground">{error ?? "Đang tải…"}</p>
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
  const canVerify = hasScope("approvals.decide");
  const clarificationArtifact = [...data.artifacts]
    .reverse()
    .find((artifact) => artifact.artifact_type === "clarification_list");
  const clarificationItems = (
    (clarificationArtifact?.content["items"] ?? []) as any[]
  ).filter((item) => item.blocking);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-col gap-4 border-b pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Link
            href="/procurement/dw01"
            className="text-xs text-muted-foreground hover:underline"
          >
            ← Danh sách hồ sơ
          </Link>
          <h1 className="mt-2 text-2xl font-semibold tracking-[-0.025em] sm:text-[1.75rem]">
            {data.title}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="secondary">
              <Tags /> {procurementTypeLabel(data.procurement_type)}
            </Badge>
            <Badge variant="outline">
              {businessDomainLabel(data.business_domain)}
            </Badge>
            <span>{data.source_pr_ref}</span>
            <span>·</span>
            <span className="font-medium text-foreground">
              {formatVnd(data.estimated_value_minor)}
            </span>
            {data.method_key && (
              <>
                <span>·</span>
                <span>{data.method_key}</span>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={badge.variant}>{badge.label}</Badge>
          <Button variant="ghost" size="icon" title="Làm mới" onClick={refresh}>
            <RefreshCw />
          </Button>
        </div>
      </div>

      {/* Stepper */}
      <Card className="overflow-hidden">
        <CardContent className="overflow-x-auto pt-5">
          <div className="flex min-w-max items-center">
            {STEPPER.map((s, i) => (
              <div key={s.key} className="flex items-center">
                <span
                  className={cn(
                    "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs",
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
                {i < STEPPER.length - 1 && (
                  <span
                    className={cn(
                      "h-px w-4",
                      i < stepIdx ? "bg-success/50" : "bg-border",
                    )}
                  />
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Nguồn hồ sơ và kiểm tra đầu vào
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {data.documents.map((document) => (
            <div
              key={document.id}
              className="grid gap-1 rounded-lg border bg-muted/20 p-3 md:grid-cols-[1fr_auto]"
            >
              <div>
                <p className="font-medium">{document.filename}</p>
                <p className="text-xs text-muted-foreground">
                  {document.content_type} ·{" "}
                  {(document.size_bytes / 1024).toFixed(1)} KiB
                </p>
              </div>
              <span className="self-center text-xs text-muted-foreground">
                Đã lưu dấu xác thực tệp
              </span>
            </div>
          ))}
          {data.intake_verified_at ? (
            <p className="flex items-center gap-2 text-success">
              <FileCheck2 className="size-4" /> Đã được một tài khoản kiểm soát
              xác minh lúc{" "}
              {new Date(data.intake_verified_at).toLocaleString("vi-VN")}.
            </p>
          ) : (
            <p className="text-warning">
              Đây là nguồn tải lên thủ công và chưa được xác minh. Hồ sơ chưa
              thể chuyển sang bước xử lý tiếp theo.
            </p>
          )}
        </CardContent>
      </Card>

      {data.notifications.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <BellRing className="size-4" /> Nhật ký thông báo Slack
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.notifications.map((notification) => (
              <div
                key={notification.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm"
              >
                <div>
                  <p className="font-medium">
                    {NOTIFICATION_LABELS[notification.event_type] ??
                      "Thông báo hồ sơ"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Hẹn gửi{" "}
                    {new Date(notification.due_at).toLocaleString("vi-VN")} · Số
                    lần thử: {notification.attempts}
                  </p>
                  {notification.last_error && (
                    <p className="mt-1 text-xs text-destructive">
                      {notification.last_error}
                    </p>
                  )}
                </div>
                <Badge
                  variant={
                    notification.status === "sent"
                      ? "success"
                      : notification.status === "failed"
                        ? "destructive"
                        : notification.status === "cancelled"
                          ? "secondary"
                          : "warning"
                  }
                >
                  {NOTIFICATION_STATUS[notification.status] ??
                    notification.status}
                </Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {data.state === "draft" && (
        <Card className="border-warning/50">
          <CardHeader>
            <CardTitle className="text-base">Xác minh hồ sơ đầu vào</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {canVerify ? (
              <>
                <p className="text-sm text-muted-foreground">
                  Xác nhận file là bản PR đã được phê duyệt trong quy trình mô
                  phỏng tải lên thủ công. Người tạo hồ sơ không được tự xác
                  minh.
                </p>
                <Input
                  placeholder="Tham chiếu phê duyệt, ví dụ APPROVAL-2026-0042"
                  value={approvalReference}
                  onChange={(e) => setApprovalReference(e.target.value)}
                />
                <Textarea
                  placeholder="Ghi chú kiểm tra nguồn (tuỳ chọn)"
                  value={verificationComment}
                  onChange={(e) => setVerificationComment(e.target.value)}
                />
                <Button
                  onClick={() => void verifyIntake()}
                  disabled={busy || !approvalReference.trim()}
                >
                  <FileCheck2 /> Xác nhận hồ sơ
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => void rejectIntake()}
                  disabled={busy || !verificationComment.trim()}
                >
                  <XCircle /> Từ chối và báo An
                </Button>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Đăng xuất và dùng tài khoản <strong>binh.tran</strong> để xác
                minh hồ sơ, sau đó quay lại tài khoản người lập.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {data.state === "intake_rejected" && (
        <Alert variant="destructive">
          <XCircle className="size-4" />
          <div className="text-sm">
            Hồ sơ đầu vào đã bị từ chối. Lý do được lưu trong nhật ký hoạt động
            và thông báo Slack đang được gửi cho người tạo hồ sơ.
          </div>
        </Alert>
      )}

      {runnable && (
        <Card className="border-primary/40">
          <CardContent className="flex flex-col items-start gap-4 pt-5 text-sm sm:flex-row sm:items-center sm:justify-between">
            <span>
              Hồ sơ đã sẵn sàng. Chạy DW01 để tạo phương án và dừng ở CP1.
            </span>
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
            Hồ sơ đang dừng để chờ quyết định phê duyệt.{" "}
            <Link className="underline" href="/approvals">
              Vào trang Phê duyệt
            </Link>{" "}
            (cần vai Người phê duyệt), duyệt xong quay lại bấm{" "}
            <strong>Làm mới</strong>.
          </div>
        </Alert>
      )}

      {data.state === "waiting_clarification" &&
        clarificationItems.length > 0 && (
          <Card className="border-warning/50">
            <CardHeader>
              <CardTitle className="text-base">
                Làm rõ đầu vào bắt buộc
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Quy trình đã dừng và chưa tạo yêu cầu phê duyệt bước 1. Hãy trả
                lời đầy đủ rồi thực hiện lại; mỗi lần xử lý đều có nhật ký
                riêng.
              </p>
              {clarificationItems.map((item) => (
                <div
                  key={String(item.id)}
                  className="space-y-2 rounded-lg border p-3"
                >
                  <p className="text-sm font-medium">{String(item.question)}</p>
                  <Textarea
                    placeholder="Câu trả lời đã được owner nghiệp vụ xác nhận"
                    value={answers[String(item.id)] ?? ""}
                    onChange={(e) =>
                      setAnswers((current) => ({
                        ...current,
                        [String(item.id)]: e.target.value,
                      }))
                    }
                  />
                  <Input
                    placeholder="Nguồn xác nhận, ví dụ email owner ngày 25/07/2026"
                    value={answerSources[String(item.id)] ?? ""}
                    onChange={(e) =>
                      setAnswerSources((current) => ({
                        ...current,
                        [String(item.id)]: e.target.value,
                      }))
                    }
                  />
                </div>
              ))}
              <Button
                onClick={() => void submitClarifications(clarificationItems)}
                disabled={
                  busy ||
                  clarificationItems.some(
                    (item) => !(answers[String(item.id)] ?? "").trim(),
                  )
                }
              >
                Lưu phản hồi làm rõ
              </Button>
            </CardContent>
          </Card>
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
              <Download /> Tải danh mục hồ sơ
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

      {data.state === "package_official" && canRun && (
        <Card className="border-primary/40">
          <CardHeader>
            <CardTitle className="text-base">
              Ghi nhận phát hành hồ sơ
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <p className="text-sm text-muted-foreground md:col-span-2">
              Vì chưa có procurement portal, hệ thống chỉ ghi nhận phát hành khi
              bạn tải lên receipt/email export hoặc bằng chứng tương đương.
            </p>
            <Input
              type="file"
              accept=".txt,.md,.pdf,.docx,.xlsx"
              onChange={(e) => setPublicationFile(e.target.files?.[0] ?? null)}
            />
            <Input
              value={publicationChannel}
              onChange={(e) => setPublicationChannel(e.target.value)}
              placeholder="Kênh phát hành"
            />
            <Input
              value={publicationRecipients}
              onChange={(e) => setPublicationRecipients(e.target.value)}
              placeholder="Người nhận/phạm vi phát hành"
            />
            <Input
              type="datetime-local"
              value={publicationAt}
              onChange={(e) => setPublicationAt(e.target.value)}
            />
            <Input
              className="md:col-span-2"
              value={publicationReference}
              onChange={(e) => setPublicationReference(e.target.value)}
              placeholder="Message-ID, số biên nhận hoặc mã tham chiếu bên ngoài"
            />
            <Button
              className="w-fit"
              onClick={() => void recordPublication()}
              disabled={
                busy ||
                !publicationFile ||
                !publicationRecipients.trim() ||
                !publicationAt ||
                !publicationReference.trim()
              }
            >
              <Send /> Ghi nhận phát hành
            </Button>
          </CardContent>
        </Card>
      )}

      {["published", "receiving_bids"].includes(data.state) && canRun && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Tiếp nhận hồ sơ nhà cung cấp
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <Input
              type="file"
              accept=".txt,.md,.pdf,.docx,.xlsx"
              onChange={(e) => setSubmissionFile(e.target.files?.[0] ?? null)}
            />
            <Input
              value={submissionSupplier}
              onChange={(e) => setSubmissionSupplier(e.target.value)}
              placeholder="Tên nhà cung cấp"
            />
            <Input
              type="datetime-local"
              value={submissionAt}
              onChange={(e) => setSubmissionAt(e.target.value)}
            />
            <select
              className="h-9 rounded-md border bg-background px-3 text-sm"
              value={submissionStatus}
              onChange={(e) =>
                setSubmissionStatus(
                  e.target.value as "on_time" | "late" | "replacement",
                )
              }
            >
              <option value="on_time">Đúng hạn</option>
              <option value="late">Nộp muộn</option>
              <option value="replacement">Bản thay thế</option>
            </select>
            <Input
              className="md:col-span-2"
              value={submissionReference}
              onChange={(e) => setSubmissionReference(e.target.value)}
              placeholder="Mã biên nhận bên ngoài (nếu có)"
            />
            <Button
              className="w-fit"
              onClick={() => void recordSubmission()}
              disabled={
                busy ||
                !submissionFile ||
                !submissionSupplier.trim() ||
                !submissionAt
              }
            >
              <PackageCheck /> Lưu hồ sơ và biên nhận
            </Button>
          </CardContent>
        </Card>
      )}

      {data.state === "published" && canRun && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Nhánh thay đổi · Addendum CP3
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <p className="text-sm text-muted-foreground md:col-span-2">
              Chỉ dùng khi cần thay đổi hồ sơ sau phát hành và trước khi tiếp
              nhận hồ sơ dự thầu. Không có thay đổi thì bỏ qua bước này.
            </p>
            <Input
              type="file"
              accept=".txt,.md,.pdf,.docx"
              onChange={(e) => setAddendumFile(e.target.files?.[0] ?? null)}
            />
            <Input
              value={addendumChange}
              onChange={(e) => setAddendumChange(e.target.value)}
              placeholder="Tóm tắt nội dung thay đổi"
            />
            <Textarea
              className="md:col-span-2"
              value={addendumImpact}
              onChange={(e) => setAddendumImpact(e.target.value)}
              placeholder="Tác động đến phạm vi, tiêu chí, thời hạn và cạnh tranh"
            />
            <Button
              variant="outline"
              className="w-fit"
              onClick={() => void submitAddendum()}
              disabled={
                busy ||
                !addendumFile ||
                !addendumChange.trim() ||
                !addendumImpact.trim()
              }
            >
              Trình addendum lên CP3
            </Button>
          </CardContent>
        </Card>
      )}

      {data.state === "cp3_pending" && (
        <Card className="border-warning/50">
          <CardHeader>
            <CardTitle className="text-base">
              CP3 · Quyết định addendum
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {canVerify ? (
              <>
                <Input
                  value={cp3Reference}
                  onChange={(e) => setCp3Reference(e.target.value)}
                  placeholder="Mã phê duyệt CP3"
                />
                <Textarea
                  value={cp3Comment}
                  onChange={(e) => setCp3Comment(e.target.value)}
                  placeholder="Nhận xét quyết định"
                />
                <div className="flex gap-2">
                  <Button
                    onClick={() => void decideCp3(true)}
                    disabled={busy || !cp3Reference.trim()}
                  >
                    Duyệt CP3
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() => void decideCp3(false)}
                    disabled={busy || !cp3Reference.trim()}
                  >
                    Từ chối
                  </Button>
                </div>
              </>
            ) : (
              <p className="text-sm">
                Đổi sang tài khoản <strong>binh.tran</strong> để quyết định CP3.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {data.state === "receiving_bids" && (
        <Card className="border-warning/50">
          <CardHeader>
            <CardTitle className="text-base">
              CP4 · Mở thầu và bàn giao đánh giá
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <p className="text-sm text-muted-foreground md:col-span-2">
              Tải biên bản mở thầu. Người lập hồ sơ không được tự xác nhận bước
              mở thầu của chính hồ sơ này.
            </p>
            {canVerify ? (
              <>
                <Input
                  type="file"
                  accept=".txt,.md,.pdf,.docx"
                  onChange={(e) => setCp4File(e.target.files?.[0] ?? null)}
                />
                <Input
                  type="datetime-local"
                  value={cp4At}
                  onChange={(e) => setCp4At(e.target.value)}
                />
                <div>
                  <label
                    htmlFor="cp4-witness"
                    className="mb-1.5 block text-sm font-medium"
                  >
                    Người chứng kiến
                  </label>
                  <TagInput
                    id="cp4-witness"
                    values={cp4Witnesses
                      .split("\n")
                      .map((item) => item.trim())
                      .filter(Boolean)}
                    onChange={(values) => setCp4Witnesses(values.join("\n"))}
                    placeholder="Nhập họ tên người chứng kiến"
                    helpText="Nhấn Enter hoặc nút Thêm sau mỗi người."
                  />
                </div>
                <Input
                  value={cp4Reference}
                  onChange={(e) => setCp4Reference(e.target.value)}
                  placeholder="Mã phê duyệt/biên bản CP4"
                />
                <Button
                  className="w-fit"
                  onClick={() => void completeCp4()}
                  disabled={
                    busy ||
                    !cp4File ||
                    !cp4At ||
                    !cp4Witnesses.trim() ||
                    !cp4Reference.trim()
                  }
                >
                  <FileCheck2 /> Xác nhận CP4 và tạo handoff
                </Button>
              </>
            ) : (
              <p className="text-sm md:col-span-2">
                Đổi sang tài khoản <strong>binh.tran</strong> để xác nhận CP4.
              </p>
            )}
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
        <CardTitle className="flex flex-col items-start gap-2 text-sm sm:flex-row sm:items-center sm:justify-between">
          <span>
            {ARTIFACT_TITLE[artifact.artifact_type] ?? artifact.artifact_type}
          </span>
          <Badge variant="secondary">
            Phiên bản {artifact.artifact_version}
          </Badge>
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
          <Row
            k="Số NCC mời"
            v={`${c.supplier_count_planned} (tối thiểu ${c.min_suppliers})`}
          />
          <Row k="Chiến lược" v={c.sourcing_strategy} />
          <Row
            k="Pháp chế/Tài chính"
            v={`${c.legal_review_required ? "Cần pháp chế" : "—"} · ${c.finance_review_required ? "Cần tài chính" : "—"}`}
          />
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
              {it.blocking && (
                <Badge variant="warning" className="ml-2">
                  Bắt buộc làm rõ
                </Badge>
              )}
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
                (đạt/không đạt) {m.text}
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
                  <Badge variant="success" className="ml-2">
                    bảo hành tại chỗ
                  </Badge>
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
              {ck.check} —{" "}
              <span className="text-muted-foreground">{ck.detail}</span>
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
          Bộ quy tắc phiên bản {c.rule_pack_version} ·{" "}
          {(c.artifacts ?? []).length} thành phần đã được xác thực. Tải bản
          chính thức ở khối phía trên.
        </p>
      );
    case "publication_record":
      return (
        <>
          <Row k="Kênh" v={c.channel} />
          <Row k="Thời điểm" v={c.published_at} />
          <Row k="Người nhận" v={c.recipient_summary} />
          <Row k="Tham chiếu" v={c.external_reference} />
          <p className="text-xs text-muted-foreground">
            Nguồn: bằng chứng tải lên thủ công · đã lưu dấu xác thực tệp
          </p>
        </>
      );
    case "addendum_draft":
      return (
        <>
          <Row k="Thay đổi" v={c.change_summary} />
          <Row k="Tác động" v={c.impact_summary} />
          <p className="text-xs text-muted-foreground">
            Tài liệu đã được lưu dấu xác thực
          </p>
        </>
      );
    case "addendum_decision":
      return (
        <>
          <Row k="Quyết định" v={c.decision} />
          <Row k="Tham chiếu CP3" v={c.approval_reference} />
          <Row k="Nhận xét" v={c.comment} />
        </>
      );
    case "submission_register":
      return (
        <div className="space-y-2">
          {(c.items ?? []).map((item: any) => (
            <div key={item.submission_id} className="rounded border p-2">
              <p className="font-medium">{item.supplier_name}</p>
              <p className="text-xs text-muted-foreground">
                {item.received_at} · {item.receipt_status} · đã xác thực tệp
              </p>
            </div>
          ))}
        </div>
      );
    case "bid_opening_record":
      return (
        <>
          <Row k="Mở thầu" v={c.opening_at} />
          <Row k="Người chứng kiến" v={(c.witnesses ?? []).join(", ")} />
          <Row k="Tham chiếu CP4" v={c.approval_reference} />
        </>
      );
    case "evaluation_handoff":
      return (
        <>
          <Row k="Số hồ sơ" v={c.submission_count} />
          <Row k="CP4" v={c.cp4_reference} />
          <p className="text-xs text-success">
            Gói bàn giao DW02 đã được tạo và lưu trong object storage.
          </p>
        </>
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
