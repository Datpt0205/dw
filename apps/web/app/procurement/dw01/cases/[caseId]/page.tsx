"use client";
/* eslint-disable @typescript-eslint/no-explicit-any -- artifact content is dynamic JSON */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  CheckCircle2,
  Circle,
  Download,
  Eye,
  FileCheck2,
  History,
  PackageCheck,
  Play,
  RefreshCw,
  Send,
  BellRing,
  Sparkles,
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
import { DW01_READONLY } from "../../../../../lib/readonly";
import { apiClient } from "../../../../../lib/session";
import { TagInput } from "../../../../../components/tag-input";
import { Modal } from "../../../../../components/modal";
import { businessDomainLabel, procurementTypeLabel } from "../../catalog";
import { ComplianceChecklist } from "../../compliance-checklist";
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

// Nhãn "file này thuộc bước nào" + thứ tự hiển thị theo dòng thời gian, để dễ
// truy vết file nào của CP nào trong ô tài liệu.
const DOC_KIND: Record<
  string,
  { label: string; variant: "secondary" | "outline" | "warning" | "success"; order: number }
> = {
  approved_pr: { label: "PR đã duyệt", variant: "secondary", order: 1 },
  publication_receipt: { label: "Bằng chứng phát hành", variant: "outline", order: 2 },
  addendum: { label: "Sửa đổi · CP3", variant: "warning", order: 3 },
  supplier_submission: { label: "Hồ sơ dự thầu", variant: "outline", order: 4 },
  bid_opening_minutes: { label: "Biên bản mở thầu · CP4", variant: "warning", order: 5 },
  other: { label: "Khác", variant: "secondary", order: 9 },
};

// Maps each stepper phase to the DOM anchor of its representative output so a
// completed step can be clicked to scroll straight to what it produced.
const STEP_ANCHOR: Record<string, string> = {
  intake: "artifact-demand_snapshot",
  cp1: "artifact-procurement_approach",
  build: "artifact-solicitation_package",
  cp2: "artifact-evaluation_criteria",
  official: "official-block",
  publication: "artifact-publication_record",
  submissions: "artifact-submission_register",
  handoff: "artifact-evaluation_handoff",
};

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

// Trim the model's "; cần owner xác nhận" caveat tail so the suggestion reads
// as a clean draft answer (the UI already frames it as "hãy kiểm tra & xác nhận").
function cleanSuggestion(s: string): string {
  return s.replace(/\s*[;,]\s*cần[^;,]*$/i, "").trim();
}

// Current local time formatted for a <input type="datetime-local"> value.
function nowLocalDatetime(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

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
  // Read-only back office: Slack is the front office for every action.
  const canRun = hasScope("tender.write") && !DW01_READONLY;
  const [data, setData] = useState<PreparationCase | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [approvalReference, setApprovalReference] = useState("");
  const [verificationComment, setVerificationComment] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [docViewer, setDocViewer] = useState<{
    filename: string;
    content: string;
  } | null>(null);
  const [historyFor, setHistoryFor] = useState<string | null>(null);
  const [showNotifs, setShowNotifs] = useState(false);
  const [publicationFile, setPublicationFile] = useState<File | null>(null);
  const [publicationChannel, setPublicationChannel] = useState("Email công vụ");
  const [publicationRecipients, setPublicationRecipients] = useState("");
  const [publicationAt, setPublicationAt] = useState("");
  const [publicationReference, setPublicationReference] = useState("");
  const [submissionFile, setSubmissionFile] = useState<File | null>(null);
  const [submissionSupplier, setSubmissionSupplier] = useState("");
  const [submissionAt, setSubmissionAt] = useState(() => nowLocalDatetime());
  const [submissionStatus, setSubmissionStatus] = useState<
    "on_time" | "late" | "replacement"
  >("on_time");
  const [submissionReference, setSubmissionReference] = useState("");
  // Bumped after each save to force-remount the file input so its displayed
  // filename resets (file inputs are uncontrolled and ignore state resets).
  const [submissionFileKey, setSubmissionFileKey] = useState(0);
  const [addendumFile, setAddendumFile] = useState<File | null>(null);
  const [addendumChange, setAddendumChange] = useState("");
  const [addendumImpact, setAddendumImpact] = useState("");
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

  // Live-ish updates for the two-tab demo: poll every 5s while visible, and
  // refresh immediately when the tab is focused/revealed so switching accounts
  // shows the other side's changes at once (no manual "Làm mới").
  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    const id = setInterval(tick, 5000);
    document.addEventListener("visibilitychange", tick);
    window.addEventListener("focus", tick);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
      window.removeEventListener("focus", tick);
    };
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
      toast.success("Đã xác minh và tự động chạy DW01 — dừng tại điểm kiểm soát.");
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
          answer: (answers[String(item.id)] ?? "").trim(),
        })),
      );
      // Auto-continue: no confusing second "Chạy DW01" click — go straight to CP1.
      await apiClient().runPreparation(caseId);
      toast.success("Đã lưu phản hồi và tiếp tục xử lý tới CP1.");
      await refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Lỗi không rõ";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function autoPublish() {
    setBusy(true);
    setError(null);
    try {
      await apiClient().autoPublishPreparation(caseId);
      toast.success("Đã gửi hồ sơ qua email và ghi nhận phát hành.");
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
      setSubmissionAt(nowLocalDatetime());
      setSubmissionFileKey((k) => k + 1);
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
  // Keep only the latest version of each artifact type on-screen; older versions
  // move into a per-type history popup so the page doesn't sprawl with v1/v2/…
  const latestByType = new Map<string, PreparationArtifact>();
  for (const a of data.artifacts) {
    const cur = latestByType.get(a.artifact_type);
    if (!cur || a.artifact_version > cur.artifact_version)
      latestByType.set(a.artifact_type, a);
  }
  const historyByType = new Map<string, PreparationArtifact[]>();
  for (const a of data.artifacts) {
    if (a.artifact_version === latestByType.get(a.artifact_type)?.artifact_version)
      continue;
    const list = historyByType.get(a.artifact_type) ?? [];
    list.push(a);
    historyByType.set(a.artifact_type, list);
  }
  for (const list of historyByType.values())
    list.sort((a, b) => b.artifact_version - a.artifact_version);
  // Hide redundant cards from the feed:
  //  - intake_verification is folded into the "Nguồn hồ sơ" card at the top.
  //  - clarification_list duplicates clarification_response once answers exist
  //    (the response shows the same questions with their answers).
  const hiddenInFeed = new Set<string>([
    "intake_verification",
    // Suppliers are shown in a combined card next to the source doc at the top.
    "supplier_input",
    "supplier_shortlist",
    // Deterministic risk checks overlap with the compliance checklist at the
    // top; kept as CP2 evidence in the data but not shown as its own card.
    "risk_compliance_check",
    // Redundant with the clarification flow: while pending, the fill-in form
    // shows the questions; once answered, "Phản hồi làm rõ" shows Q+A. The
    // completeness count is already on the demand snapshot header.
    "completeness_report",
    "clarification_list",
    // The official manifest is just a pointer to the download block above.
    "official_package_manifest",
    // Shown inline under the intake form instead of far down the feed.
    "submission_register",
    // Merged in-place into single cards (kept at their process position in the
    // feed): CP3 = addendum_draft + addendum_decision; CP4 = bid_opening_record
    // + evaluation_handoff. The "_draft"/"_record" halves stay visible and carry
    // the merged render; the decision/handoff halves are folded in.
    "addendum_decision",
    "evaluation_handoff",
  ]);
  const artifacts = [...latestByType.values()]
    .filter((a) => !hiddenInFeed.has(a.artifact_type))
    .sort(
      (a, b) =>
        ARTIFACT_ORDER.indexOf(a.artifact_type) -
        ARTIFACT_ORDER.indexOf(b.artifact_type),
    );
  const intakeVerification = latestByType.get("intake_verification")
    ?.content as Record<string, any> | undefined;
  const supplierInput = latestByType.get("supplier_input")?.content as
    | Record<string, any>
    | undefined;
  const supplierShortlist = latestByType.get("supplier_shortlist")?.content as
    | Record<string, any>
    | undefined;
  const submissionItems = (latestByType.get("submission_register")?.content[
    "items"
  ] ?? []) as any[];
  const addendumDecision = latestByType.get("addendum_decision")?.content as
    | Record<string, any>
    | undefined;
  const handoff = latestByType.get("evaluation_handoff")?.content as
    | Record<string, any>
    | undefined;
  const official = latestByType.get("official_package_manifest");
  const runnable = data.state === "intake_ready" && canRun;
  const hasRunBefore = latestByType.has("demand_snapshot");
  const canVerify = hasScope("approvals.decide") && !DW01_READONLY;
  const clarificationItems = (
    (latestByType.get("clarification_list")?.content["items"] ?? []) as any[]
  ).filter((item) => item.blocking);
  // CP1 gate blockers that are NOT about clarifications (e.g. too few suppliers,
  // missing budget) — surfaced so a failed gate is never a silent dead-end.
  const approachArtifact = latestByType.get("procurement_approach");
  const gateReasons = (
    ((approachArtifact?.content["gate"] as any)?.reasons ?? []) as string[]
  ).filter((r) => !/làm rõ/i.test(r));
  const stuckBeforeCp1 =
    data.state === "waiting_clarification" &&
    clarificationItems.length === 0 &&
    gateReasons.length > 0;
  // CP2 gate blockers (weighted total ≠ 100, shortlist below minimum, missing
  // sections) — same "never a silent dead-end" treatment as CP1.
  const gateReasonsCp2 = (((latestByType.get("solicitation_package")?.content[
    "gate"
  ] as any)?.reasons ?? []) as string[]).filter(Boolean);
  const stuckBeforeCp2 =
    data.state === "package_ready" && gateReasonsCp2.length > 0;

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
          {data.notifications.length > 0 && (
            <Button
              variant="ghost"
              size="icon"
              title="Nhật ký thông báo Slack"
              onClick={() => setShowNotifs(true)}
              className="relative"
            >
              <BellRing />
              <span className="absolute right-0.5 top-0.5 flex size-4 items-center justify-center rounded-full bg-primary text-[10px] font-semibold text-primary-foreground">
                {data.notifications.length}
              </span>
            </Button>
          )}
          <Button variant="ghost" size="icon" title="Làm mới" onClick={refresh}>
            <RefreshCw />
          </Button>
        </div>
      </div>

      {/* Stepper */}
      <Card className="overflow-hidden">
        <CardContent className="overflow-x-auto pt-5">
          <div className="flex min-w-max items-center">
            {STEPPER.map((s, i) => {
              const reachable = i <= stepIdx;
              const anchor = STEP_ANCHOR[s.key];
              // On a completed case the final (current) step is also "done".
              const flowDone = data.state === "completed";
              const done = i < stepIdx || (flowDone && i === stepIdx);
              const current = i === stepIdx && !flowDone;
              return (
              <div key={s.key} className="flex items-center">
                <button
                  type="button"
                  disabled={!reachable || !anchor}
                  onClick={() => {
                    if (anchor)
                      document
                        .getElementById(anchor)
                        ?.scrollIntoView({ behavior: "smooth", block: "center" });
                  }}
                  title={
                    reachable && anchor
                      ? "Xem lại bước này"
                      : "Chưa tới bước này"
                  }
                  className={cn(
                    "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs transition",
                    done
                      ? "bg-success/15 text-success"
                      : current
                        ? "bg-primary/15 font-medium text-primary"
                        : "bg-muted text-muted-foreground",
                    reachable && anchor
                      ? "cursor-pointer hover:ring-2 hover:ring-primary/30"
                      : "cursor-default",
                  )}
                >
                  {done ? (
                    <CheckCircle2 className="size-3.5" />
                  ) : (
                    <Circle className="size-3.5" />
                  )}
                  {s.label}
                </button>
                {i < STEPPER.length - 1 && (
                  <span
                    className={cn(
                      "h-px w-4",
                      done ? "bg-success/50" : "bg-border",
                    )}
                  />
                )}
              </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <ComplianceChecklist caseData={data} />

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div
        className={cn(
          "grid items-start gap-4",
          (supplierInput || supplierShortlist) && "lg:grid-cols-2",
        )}
      >
        <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Tài liệu hồ sơ (theo bước)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {[...data.documents]
            .sort(
              (a, b) =>
                (DOC_KIND[(a as any).kind]?.order ?? 8) -
                (DOC_KIND[(b as any).kind]?.order ?? 8),
            )
            .map((document) => {
            const text = (document as any).text_content as string | undefined;
            const kind =
              DOC_KIND[(document as any).kind] ??
              ({ label: "Khác", variant: "secondary" } as const);
            return (
              <div
                key={document.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-muted/20 px-3 py-2"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <Badge variant={kind.variant} className="shrink-0">
                    {kind.label}
                  </Badge>
                  <span className="truncate font-medium">
                    {document.filename}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {(document.size_bytes / 1024).toFixed(1)} KiB
                  </span>
                </div>
                {text ? (
                  <button
                    type="button"
                    onClick={() =>
                      setDocViewer({ filename: document.filename, content: text })
                    }
                    className="inline-flex shrink-0 items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium transition hover:bg-muted"
                  >
                    <Eye className="size-3.5" /> Xem nội dung
                  </button>
                ) : (
                  <span className="shrink-0 text-xs text-muted-foreground">
                    (không xem trước được)
                  </span>
                )}
              </div>
            );
          })}
          {data.intake_verified_at ? (
            <div className="rounded-lg border border-success/30 bg-success/5 p-2.5">
              <p className="flex items-center gap-2 text-xs font-medium text-success">
                <FileCheck2 className="size-3.5" /> Đã xác minh đầu vào lúc{" "}
                {new Date(data.intake_verified_at).toLocaleString("vi-VN")}
                {intakeVerification?.approval_reference
                  ? ` · Tham chiếu ${intakeVerification.approval_reference}`
                  : ""}
              </p>
            </div>
          ) : (
            <p className="text-xs text-warning">
              Nguồn tải lên thủ công, chưa được xác minh — chưa thể chuyển bước
              tiếp theo.
            </p>
          )}
        </CardContent>
      </Card>

        {(supplierInput || supplierShortlist) && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Nhà cung cấp</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {/* Shortlist = candidates carried forward (no screening yet;
                  eligibility is verified at CP2), so we show ONE list. */}
              <ul className="list-disc space-y-0.5 pl-5">
                {(
                  (supplierShortlist?.shortlist ??
                    supplierInput?.suppliers ??
                    []) as any[]
                ).map((s: any, i: number) => (
                  <li
                    key={String(s.name ?? i)}
                    className="flex items-center gap-2"
                  >
                    {String(s.name)}
                    {s.on_site_warranty && (
                      <Badge variant="success">bảo hành tại chỗ</Badge>
                    )}
                  </li>
                ))}
              </ul>
              {(supplierShortlist?.excluded ?? []).length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Loại:{" "}
                  {(supplierShortlist?.excluded ?? [])
                    .map((e: any) => e.name)
                    .join(", ")}
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                {supplierShortlist
                  ? "Danh sách mời — eligibility sẽ được xác minh ở CP2."
                  : "Ứng viên đề xuất khi lập hồ sơ."}
              </p>
            </CardContent>
          </Card>
        )}
      </div>

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
                Xác minh do <strong>Bình</strong> thực hiện trên thẻ Slack
                (nút «Xác minh &amp; chạy DW01»).
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
              {hasRunBefore
                ? "Đã lưu phản hồi làm rõ. Tiếp tục xử lý để tạo phương án và dừng ở CP1."
                : "Hồ sơ đã sẵn sàng. Chạy DW01 để tạo phương án và dừng ở CP1."}
            </span>
            <Button onClick={() => void runDw01()} disabled={busy}>
              <Play />{" "}
              {busy
                ? "Đang xử lý…"
                : hasRunBefore
                  ? "Tiếp tục xử lý"
                  : "Chạy DW01"}
            </Button>
          </CardContent>
        </Card>
      )}

      {stuckBeforeCp1 && (
        <Alert variant="destructive">
          <XCircle className="size-4" />
          <div className="space-y-1.5 text-sm">
            <p>
              <strong>Chưa qua được CP1</strong> — cần xử lý các điểm sau (không
              phải làm rõ đầu vào):
            </p>
            <ul className="list-disc space-y-0.5 pl-5">
              {gateReasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
            <p className="text-xs text-muted-foreground">
              Số nhà cung cấp ứng viên được nhập khi tạo hồ sơ. Với gói đấu
              thầu rộng rãi/chào giá cạnh tranh cần tối thiểu 3 nhà cung cấp —
              hãy tạo lại hồ sơ với đủ danh sách, hoặc điều chỉnh giá trị gói.
            </p>
          </div>
        </Alert>
      )}

      {stuckBeforeCp2 && (
        <Alert variant="destructive">
          <XCircle className="size-4" />
          <div className="space-y-1.5 text-sm">
            <p>
              <strong>Chưa qua được CP2</strong> — bộ hồ sơ chưa hợp lệ, cần xử
              lý:
            </p>
            <ul className="list-disc space-y-0.5 pl-5">
              {gateReasonsCp2.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>
        </Alert>
      )}

      {!DW01_READONLY &&
        data.state === "waiting_clarification" &&
        clarificationItems.length > 0 && (
          <Card className="border-warning/50">
            <CardHeader>
              <CardTitle className="text-base">
                Làm rõ đầu vào ({clarificationItems.length} mục)
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                AI phát hiện vài điểm chưa rõ trong hồ sơ. Xác nhận câu trả lời
                cho từng điểm — có thể bấm <b>Dùng gợi ý của AI</b> rồi chỉnh
                lại. Lưu xong hệ thống tự chạy tiếp tới CP1.
              </p>
              {clarificationItems.map((item, idx) => {
                const id = String(item.id);
                const suggestion = cleanSuggestion(
                  String(item.suggested_answer ?? ""),
                );
                const value = answers[id] ?? "";
                return (
                  <div key={id} className="space-y-2 rounded-lg border p-3">
                    <p className="text-sm font-medium">
                      <span className="mr-1.5 text-muted-foreground">
                        {idx + 1}.
                      </span>
                      {String(item.question)}
                    </p>
                    <Textarea
                      rows={2}
                      placeholder="Nhập câu trả lời đã được owner nghiệp vụ xác nhận…"
                      value={value}
                      onChange={(e) =>
                        setAnswers((current) => ({
                          ...current,
                          [id]: e.target.value,
                        }))
                      }
                    />
                    {suggestion && value.trim() !== suggestion && (
                      <button
                        type="button"
                        onClick={() =>
                          setAnswers((current) => ({
                            ...current,
                            [id]: suggestion,
                          }))
                        }
                        className="inline-flex items-start gap-1.5 rounded-md bg-[#eef5fb] px-2.5 py-1.5 text-left text-xs leading-5 text-primary transition hover:bg-[#e2eefb]"
                      >
                        <Sparkles className="mt-0.5 size-3.5 shrink-0" />
                        <span>
                          <b>Dùng gợi ý của AI:</b> {suggestion}
                        </span>
                      </button>
                    )}
                  </div>
                );
              })}
              <Button
                onClick={() => void submitClarifications(clarificationItems)}
                disabled={
                  busy ||
                  clarificationItems.some(
                    (item) => !(answers[String(item.id)] ?? "").trim(),
                  )
                }
              >
                {busy ? "Đang lưu và xử lý…" : "Lưu và tiếp tục tới CP1"}
              </Button>
            </CardContent>
          </Card>
        )}

      {official && (
        <Card id="official-block" className="scroll-mt-24 border-success/40">
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
            <div className="flex flex-col gap-2 rounded-lg border border-primary/30 bg-primary/5 p-3 md:col-span-2 sm:flex-row sm:items-center sm:justify-between">
              <span className="text-sm">
                <strong>Phát hành tự động:</strong> gửi hồ sơ mời thầu qua email
                tới các nhà cung cấp trong shortlist và tự ghi nhận.
              </span>
              <Button
                className="w-fit shrink-0"
                onClick={() => void autoPublish()}
                disabled={busy}
              >
                <Send /> {busy ? "Đang gửi…" : "Phát hành qua email"}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground md:col-span-2">
              Hoặc ghi nhận thủ công: tải lên receipt/email export làm bằng
              chứng phát hành.
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
            <p className="text-xs text-muted-foreground md:col-span-2">
              Có thể tiếp nhận nhiều nhà cung cấp — nhập & lưu cho từng hồ sơ.
              Khi đã đủ, chuyển sang xác nhận mở thầu (CP4).
            </p>
            <Input
              key={submissionFileKey}
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
              title={
                !submissionFile
                  ? "Cần chọn tệp hồ sơ dự thầu"
                  : !submissionSupplier.trim()
                    ? "Cần nhập tên nhà cung cấp"
                    : !submissionAt
                      ? "Cần chọn thời điểm nhận"
                      : "Lưu hồ sơ này vào sổ tiếp nhận"
              }
              disabled={
                busy ||
                !submissionFile ||
                !submissionSupplier.trim() ||
                !submissionAt
              }
            >
              <PackageCheck /> Lưu hồ sơ và biên nhận
            </Button>
            {submissionItems.length > 0 && (
              <div className="md:col-span-2">
                <p className="mb-1.5 text-xs font-medium text-muted-foreground">
                  Đã tiếp nhận ({submissionItems.length})
                </p>
                <div className="space-y-1.5">
                  {submissionItems.map((item: any) => (
                    <div
                      key={String(item.submission_id ?? item.supplier_name)}
                      className="rounded border p-2 text-sm"
                    >
                      <span className="font-medium">{item.supplier_name}</span>
                      <span className="ml-2 text-xs text-muted-foreground">
                        {item.received_at
                          ? new Date(item.received_at).toLocaleString("vi-VN")
                          : ""}{" "}
                        · {item.receipt_status} · đã xác thực tệp
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
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
        <Alert>
          <FileCheck2 className="size-4" />
          <div className="text-sm">
            Addendum đang chờ <strong>quyết định CP3</strong> (người có thẩm quyền
            ≠ người tạo).{" "}
            <Link className="underline" href="/approvals">
              Mở trang Phê duyệt
            </Link>{" "}
            để duyệt/từ chối — giống các bước CP1, CP2.
          </div>
        </Alert>
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
                CP4 do <strong>Bình</strong> xác nhận trên thẻ Slack.
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
        {artifacts.map((a) => {
          // CP3 / CP4 render as merged cards in their process position.
          if (a.artifact_type === "addendum_draft")
            return (
              <Cp3Card
                key={a.id}
                draft={a.content as Record<string, any>}
                decision={addendumDecision}
              />
            );
          if (a.artifact_type === "bid_opening_record")
            return (
              <Cp4Card
                key={a.id}
                opening={a.content as Record<string, any>}
                handoff={handoff}
              />
            );
          return (
            <ArtifactCard
              key={a.id}
              artifact={a}
              historyCount={historyByType.get(a.artifact_type)?.length ?? 0}
              onOpenHistory={() => setHistoryFor(a.artifact_type)}
            />
          );
        })}
      </div>

      <Modal
        open={docViewer !== null}
        onClose={() => setDocViewer(null)}
        title={docViewer?.filename ?? ""}
        subtitle="Nội dung tệp nguồn đã tải lên"
      >
        <DocPreview content={docViewer?.content ?? ""} />
      </Modal>

      <Modal
        open={showNotifs}
        onClose={() => setShowNotifs(false)}
        title="Nhật ký thông báo Slack"
        subtitle="Riêng khâu xác minh đầu vào (intake). Phê duyệt CP1–CP4 xem ở trang Phê duyệt."
      >
        <div className="space-y-2">
          {data.notifications.map((notification) => {
            const cancelled = notification.status === "cancelled";
            const failed = notification.status === "failed";
            return (
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
                  {cancelled && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      Không cần gửi — hồ sơ đã được xử lý kịp trước khi nhắc
                      việc đến hạn (đây là hành vi đúng, không phải lỗi).
                    </p>
                  )}
                  {failed && notification.last_error && (
                    <p className="mt-1 text-xs text-destructive">
                      {notification.last_error}
                    </p>
                  )}
                </div>
                <Badge
                  variant={
                    notification.status === "sent"
                      ? "success"
                      : failed
                        ? "destructive"
                        : cancelled
                          ? "secondary"
                          : "warning"
                  }
                >
                  {cancelled
                    ? "Không cần gửi"
                    : NOTIFICATION_STATUS[notification.status] ??
                      notification.status}
                </Badge>
              </div>
            );
          })}
        </div>
      </Modal>

      <Modal
        open={historyFor !== null}
        onClose={() => setHistoryFor(null)}
        title={`Lịch sử: ${ARTIFACT_TITLE[historyFor ?? ""] ?? historyFor ?? ""}`}
        subtitle="Các phiên bản cũ hơn (mới nhất đang hiển thị ngoài trang)"
      >
        <div className="space-y-3">
          {(historyByType.get(historyFor ?? "") ?? []).map((a) => (
            <div key={a.id} className="rounded-lg border p-3">
              <Badge variant="secondary" className="mb-2">
                Phiên bản {a.artifact_version}
              </Badge>
              <div className="space-y-1.5 text-sm">
                {renderArtifact(
                  a.artifact_type,
                  a.content as Record<string, any>,
                )}
              </div>
            </div>
          ))}
        </div>
      </Modal>
    </div>
  );
}

// CP3 = addendum draft + its decision, merged into one card.
function Cp3Card({
  draft,
  decision,
}: {
  draft: Record<string, any>;
  decision?: Record<string, any>;
}) {
  return (
    <Card id="artifact-addendum_draft" className="scroll-mt-24">
      <CardHeader>
        <CardTitle className="text-sm">Sửa đổi HSMT (CP3)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <Row k="Nội dung thay đổi" v={draft.change_summary} />
        <Row k="Tác động" v={draft.impact_summary} />
        <div className="border-t pt-2">
          {decision ? (
            <div className="space-y-1">
              <Badge
                variant={
                  decision.decision === "approved" ? "success" : "destructive"
                }
              >
                {decision.decision === "approved"
                  ? "Đã duyệt CP3"
                  : "Đã từ chối"}
              </Badge>
              <Row k="Tham chiếu CP3" v={decision.approval_reference} />
              {String(decision.comment ?? "") && (
                <Row k="Nhận xét" v={decision.comment} />
              )}
            </div>
          ) : (
            <Badge variant="warning">Chờ quyết định CP3</Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Văn bản sửa đổi lưu trong «Tài liệu hồ sơ» (nhãn «Sửa đổi · CP3»).
        </p>
      </CardContent>
    </Card>
  );
}

// CP4 = bid-opening record + the DW02 handoff package, merged into one card.
function Cp4Card({
  opening,
  handoff,
}: {
  opening: Record<string, any>;
  handoff?: Record<string, any>;
}) {
  const openedAt = opening.opening_at ? new Date(opening.opening_at) : null;
  return (
    <Card id="artifact-evaluation_handoff" className="scroll-mt-24">
      <CardHeader>
        <CardTitle className="text-sm">
          Mở thầu & bàn giao đánh giá (CP4)
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <Row
          k="Mở thầu"
          v={
            openedAt && !isNaN(openedAt.getTime())
              ? openedAt.toLocaleString("vi-VN")
              : opening.opening_at
          }
        />
        <Row k="Người chứng kiến" v={(opening.witnesses ?? []).join(", ")} />
        <Row k="Tham chiếu CP4" v={opening.approval_reference} />
        <div className="border-t pt-2">
          {handoff ? (
            <div className="space-y-1">
              <Badge variant="success">Đã bàn giao cho DW02</Badge>
              <Row k="Số hồ sơ bàn giao" v={handoff.submission_count} />
              <p className="text-xs text-success">
                Gói bàn giao đã được tạo và lưu trong object storage.
              </p>
            </div>
          ) : (
            <Badge variant="warning">Chưa tạo gói bàn giao</Badge>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function ArtifactCard({
  artifact,
  historyCount,
  onOpenHistory,
}: {
  artifact: PreparationArtifact;
  historyCount: number;
  onOpenHistory: () => void;
}) {
  const c = artifact.content as Record<string, any>;
  return (
    <Card id={`artifact-${artifact.artifact_type}`} className="scroll-mt-24">
      <CardHeader>
        <CardTitle className="flex flex-col items-start gap-2 text-sm sm:flex-row sm:items-center sm:justify-between">
          <span>
            {ARTIFACT_TITLE[artifact.artifact_type] ?? artifact.artifact_type}
          </span>
          {historyCount > 0 && (
            <button
              type="button"
              onClick={onOpenHistory}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-normal text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              <History className="size-3.5" /> {historyCount} phiên bản cũ
            </button>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5 text-sm">
        {renderArtifact(artifact.artifact_type, c)}
      </CardContent>
    </Card>
  );
}

// Beautify a plain-text / lightweight-markdown source doc for the preview popup:
// headings (# / ##), bullet lines, and blank-line paragraph breaks.
function DocPreview({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  return (
    <div className="space-y-1.5 text-sm leading-6">
      {lines.map((raw, i) => {
        const line = raw.trimEnd();
        if (!line.trim()) return <div key={i} className="h-2" />;
        const h = /^(#{1,3})\s+(.*)$/.exec(line);
        if (h) {
          const size =
            (h[1] ?? "").length === 1
              ? "text-base font-semibold"
              : "text-sm font-semibold";
          return (
            <p key={i} className={`${size} mt-1`}>
              {h[2] ?? ""}
            </p>
          );
        }
        if (/^\s*[-•*]\s+/.test(line)) {
          return (
            <p key={i} className="flex gap-2 pl-1">
              <span className="text-muted-foreground">•</span>
              <span>{line.replace(/^\s*[-•*]\s+/, "")}</span>
            </p>
          );
        }
        return <p key={i}>{line}</p>;
      })}
    </div>
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
          {c.gate && (
            <div className="border-t pt-2">
              {c.gate.passed ? (
                <Badge variant="success">Đủ điều kiện trình CP1</Badge>
              ) : (
                <div className="space-y-1">
                  <Badge variant="destructive">Chưa đủ điều kiện CP1</Badge>
                  <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
                    {(c.gate.reasons ?? []).map((r: string, i: number) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
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
    case "clarification_response":
      return (
        <div className="space-y-2.5">
          <p className="flex items-start gap-1.5 rounded-md bg-[#eef5fb] px-2.5 py-1.5 text-xs leading-5 text-primary">
            <Sparkles className="mt-0.5 size-3.5 shrink-0" />
            <span>
              AI bóc PR phát hiện <b>{(c.items ?? []).length} điểm chưa rõ</b>;
              nhân viên đã bổ sung câu trả lời bên dưới.
            </span>
          </p>
          <ul className="space-y-2">
            {((c.items ?? []) as any[]).map((it: any) => (
              <li key={String(it.id)} className="rounded-lg border p-2.5">
                <p className="text-sm font-medium">{String(it.question)}</p>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  {String(it.answer)}
                </p>
                {String(it.source_note ?? "") && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Nguồn: {String(it.source_note)}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      );
    case "intake_verification":
      return (
        <>
          <Row k="Kết luận" v="Đã xác minh đầu vào" />
          <Row k="Tham chiếu" v={c.approval_reference} />
          <p className="text-xs text-muted-foreground">{c.declaration}</p>
        </>
      );
    case "supplier_input":
      return (c.suppliers ?? []).length === 0 ? (
        <p className="text-muted-foreground">Chưa nhập nhà cung cấp ứng viên.</p>
      ) : (
        <ul className="list-disc space-y-0.5 pl-5">
          {((c.suppliers ?? []) as any[]).map((s: any, i: number) => (
            <li key={String(s.name ?? i)}>{String(s.name)}</li>
          ))}
        </ul>
      );
    case "evaluation_criteria":
      return (
        <div className="space-y-2">
          {c.source === "ai" && (
            <Badge variant="success">
              <span className="flex items-center gap-1">
                <Sparkles className="size-3" /> AI đề xuất trọng số
              </span>
            </Badge>
          )}
          <p className="text-xs text-muted-foreground">
            Tổng trọng số: {c.weighted_total} · tiêu chí đạt/không đạt lấy từ
            bộ quy tắc
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
        </div>
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
        <div className="space-y-2">
          <Badge variant="secondary">Kiểm tra cố định theo quy tắc</Badge>
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
        </div>
      );
    case "demand_snapshot": {
      const reqs = (c.requirements ?? []) as any[];
      const aiExtracted = String(c.extraction_source ?? "") === "ai";
      return (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={aiExtracted ? "success" : "secondary"}>
              {aiExtracted ? (
                <span className="flex items-center gap-1">
                  <Sparkles className="size-3" /> AI bóc tách
                </span>
              ) : (
                "Tách theo quy tắc"
              )}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {reqs.length} yêu cầu · {(c.unknowns ?? []).length} điểm cần làm rõ
            </span>
          </div>
          <Row k="Giá trị" v={c.estimated_value} />
          <Row k="Thời hạn" v={c.deadline} />
          {reqs.length > 0 && (
            <ul className="space-y-1.5 border-t pt-2">
              {reqs.map((r: any, i: number) => (
                <li
                  key={String(r.code ?? i)}
                  className="flex items-start gap-2 text-sm"
                >
                  {r.code && (
                    <span className="mt-0.5 shrink-0 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
                      {String(r.code)}
                    </span>
                  )}
                  <span className="min-w-0">
                    {String(r.text ?? "")}
                    {r.kind === "mandatory" && (
                      <span className="ml-1.5 text-[11px] font-medium text-amber-600">
                        bắt buộc
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      );
    }
    case "solicitation_package":
      return (
        <div className="space-y-2.5">
          <div className="flex flex-wrap items-center gap-2">
            {c.drafted_by === "ai" && (
              <Badge variant="success">
                <span className="flex items-center gap-1">
                  <Sparkles className="size-3" /> AI soạn thảo
                </span>
              </Badge>
            )}
            {c.gate &&
              (c.gate.passed ? (
                <Badge variant="success">Đủ điều kiện trình CP2</Badge>
              ) : (
                <Badge variant="destructive">Chưa đủ điều kiện CP2</Badge>
              ))}
          </div>
          {c.gate && !c.gate.passed && (c.gate.reasons ?? []).length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-destructive">
              {(c.gate.reasons ?? []).map((r: string, i: number) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
          <div>
            <p className="font-medium">Phạm vi cung cấp</p>
            <p className="text-muted-foreground">{c.scope}</p>
          </div>
          {(c.requirements ?? []).length > 0 && (
            <div>
              <p className="font-medium">
                Yêu cầu kỹ thuật ({(c.requirements ?? []).length})
              </p>
              <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
                {(c.requirements ?? []).map((r: string, i: number) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          )}
          {c.commercial_terms && (
            <div>
              <p className="font-medium">Điều khoản thương mại</p>
              <ul className="space-y-0.5 text-muted-foreground">
                <li>Thanh toán: {c.commercial_terms.payment}</li>
                <li>Giao hàng: {c.commercial_terms.delivery}</li>
                <li>Thuế: {c.commercial_terms.tax}</li>
              </ul>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            Cấu trúc hồ sơ: {(c.response_structure ?? []).join(" · ")}
          </p>
        </div>
      );
    case "official_package_manifest":
      return (
        <p className="text-xs text-muted-foreground">
          Bộ quy tắc phiên bản {c.rule_pack_version} ·{" "}
          {(c.artifacts ?? []).length} thành phần đã được xác thực. Tải bản
          chính thức ở khối phía trên.
        </p>
      );
    case "publication_record": {
      const auto = c.source_mode === "auto_email";
      const when = new Date(c.published_at);
      return (
        <>
          <Row k="Kênh" v={c.channel} />
          <Row
            k="Thời điểm"
            v={
              isNaN(when.getTime())
                ? c.published_at
                : when.toLocaleString("vi-VN")
            }
          />
          <Row k="Người nhận" v={c.recipient_summary} />
          {auto && c.sent_to && <Row k="Gửi tới" v={c.sent_to} />}
          <div className="flex gap-2">
            <span className="w-32 shrink-0 text-muted-foreground">
              {auto ? "Mã thư (Message-ID)" : "Tham chiếu"}
            </span>
            <span className="min-w-0 break-all font-mono text-xs">
              {c.external_reference}
            </span>
          </div>
          <p className="text-xs text-muted-foreground">
            {auto
              ? "Đã gửi tự động qua email công vụ. Có thể tra Message-ID này trong hộp thư."
              : "Nguồn: bằng chứng tải lên thủ công · đã lưu dấu xác thực tệp"}
          </p>
        </>
      );
    }
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
