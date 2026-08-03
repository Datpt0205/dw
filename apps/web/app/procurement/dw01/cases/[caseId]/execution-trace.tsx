"use client";
/* eslint-disable @typescript-eslint/no-explicit-any -- artifact content is dynamic JSON */

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BookOpenCheck,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileText,
  GitBranch,
  ShieldAlert,
} from "lucide-react";
import type { PreparationArtifact } from "@dw/api-client";
import { Badge, Card, CardContent, cn } from "@dw/ui";
import { apiClient } from "../../../../../lib/session";

/**
 * "Work tree" of one DW01 run: every executed step as a node, and for the
 * steps that consulted the knowledge base (RAG) — which documents and which
 * passages grounded the draft. Click a node to expand its evidence.
 *
 * Data is read straight from the persisted artifacts (legal_basis /
 * policy_basis / references written by the workflow nodes) — nothing here is
 * re-generated for display.
 */

interface Citation {
  source_document_id: string;
  source_version: string;
  quote: string;
  relevance_score: number;
  classification: string;
}

// Ordered pipeline steps (artifact_type → node label).
const STEP_TITLE: Record<string, string> = {
  intake_verification: "Xác minh hồ sơ đầu vào",
  supplier_input: "Nguồn nhà cung cấp ứng viên",
  demand_snapshot: "Chuẩn hoá nhu cầu (bóc PR)",
  completeness_report: "Kiểm tra tính đầy đủ",
  clarification_list: "Câu hỏi làm rõ",
  clarification_response: "Phản hồi làm rõ",
  procurement_approach: "Phương án mua sắm — CP1",
  solicitation_package: "Soạn HSMT/RFQ",
  evaluation_criteria: "Tiêu chí đánh giá — CP2",
  supplier_shortlist: "Shortlist nhà cung cấp",
  risk_compliance_check: "Kiểm tra rủi ro & tuân thủ",
  official_package_manifest: "Khoá bộ hồ sơ chính thức",
  publication_record: "Phát hành hồ sơ",
  addendum_draft: "Văn bản sửa đổi — CP3",
  addendum_decision: "Quyết định CP3",
  submission_register: "Tiếp nhận hồ sơ dự thầu",
  bid_opening_record: "Mở thầu — CP4",
  evaluation_handoff: "Bàn giao đánh giá (DW02)",
};
const STEP_ORDER = Object.keys(STEP_TITLE);

// Citation buckets a step may carry.
const CITE_KEYS: { key: string; label: string }[] = [
  { key: "legal_basis", label: "Căn cứ pháp lý" },
  { key: "policy_basis", label: "Quy chế nội bộ" },
  { key: "references", label: "Tài liệu tham chiếu" },
];

function citationsOf(
  content: Record<string, any>,
): { label: string; items: Citation[] }[] {
  return CITE_KEYS.map(({ key, label }) => ({
    label,
    items: Array.isArray(content[key]) ? (content[key] as Citation[]) : [],
  })).filter((group) => group.items.length > 0);
}

export function ExecutionTrace({
  artifacts,
}: {
  artifacts: PreparationArtifact[];
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [docTitles, setDocTitles] = useState<Map<string, string>>(new Map());

  // Resolve source_document_id → human title via the knowledge catalogue.
  // Best-effort: without the scope the trace still renders with short ids.
  useEffect(() => {
    apiClient()
      .listKnowledgeDocuments()
      .then((docs) =>
        setDocTitles(new Map(docs.map((d) => [d.document_id, d.title]))),
      )
      .catch(() => undefined);
  }, []);

  const steps = useMemo(() => {
    const latest = new Map<string, PreparationArtifact>();
    for (const artifact of artifacts) {
      const existing = latest.get(artifact.artifact_type);
      if (!existing || artifact.artifact_version > existing.artifact_version) {
        latest.set(artifact.artifact_type, artifact);
      }
    }
    return STEP_ORDER.filter((type) => latest.has(type)).map((type) => ({
      type,
      artifact: latest.get(type)!,
    }));
  }, [artifacts]);

  if (steps.length === 0) return null;

  return (
    <Card>
      <div className="flex items-center gap-2 border-b px-5 py-4 sm:px-6">
        <GitBranch className="size-4 text-primary" />
        <h2 className="font-semibold">Vết thực thi</h2>
        <span className="text-xs text-muted-foreground">
          từng bước Digital Worker đã chạy — bấm để xem căn cứ
        </span>
      </div>
      <CardContent className="pt-4">
        <ol className="relative ml-2 space-y-1 border-l pl-5">
          {steps.map(({ type, artifact }) => {
            const content = artifact.content as Record<string, any>;
            const cites = citationsOf(content);
            const citeCount = cites.reduce((n, g) => n + g.items.length, 0);
            const gate = content.gate as
              { passed: boolean; reasons?: string[] } | undefined;
            const grounded = content.grounding_status as string | undefined;
            const hasDetail = citeCount > 0 || gate !== undefined;
            const open = expanded === type;
            return (
              <li key={type} className="relative pb-2">
                <span className="absolute -left-[27px] top-1 flex size-4 items-center justify-center rounded-full bg-background">
                  <CheckCircle2 className="size-4 text-success" />
                </span>
                <button
                  type="button"
                  disabled={!hasDetail}
                  onClick={() => setExpanded(open ? null : type)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm",
                    hasDetail && "transition-colors hover:bg-accent/50",
                  )}
                >
                  {hasDetail ? (
                    open ? (
                      <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
                    )
                  ) : (
                    <span className="w-3.5 shrink-0" />
                  )}
                  <span className="font-medium">{STEP_TITLE[type]}</span>
                  <span className="text-xs text-muted-foreground">
                    v{artifact.artifact_version}
                  </span>
                  {gate !== undefined && (
                    <Badge variant={gate.passed ? "success" : "warning"}>
                      gate {gate.passed ? "đạt" : "chưa đạt"}
                    </Badge>
                  )}
                  {citeCount > 0 && (
                    <Badge variant="secondary">
                      <BookOpenCheck className="mr-1 size-3" />
                      {citeCount} căn cứ
                    </Badge>
                  )}
                  {grounded === "not_available" && (
                    <Badge variant="warning">
                      <ShieldAlert className="mr-1 size-3" /> thiếu căn cứ
                    </Badge>
                  )}
                </button>

                {open && (
                  <div className="ml-6 mt-1 space-y-3 rounded-lg border bg-muted/30 p-3">
                    {gate !== undefined && !gate.passed && (
                      <div className="space-y-1">
                        <p className="flex items-center gap-1.5 text-xs font-semibold text-amber-600">
                          <AlertTriangle className="size-3.5" /> Lý do gate chưa
                          đạt
                        </p>
                        {(gate.reasons ?? []).map((reason) => (
                          <p
                            key={reason}
                            className="text-xs text-muted-foreground"
                          >
                            • {reason}
                          </p>
                        ))}
                      </div>
                    )}
                    {cites.map((group) => (
                      <div key={group.label} className="space-y-2">
                        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          {group.label}
                        </p>
                        {group.items.map((cite, index) => (
                          <div
                            key={`${cite.source_document_id}-${index}`}
                            className="rounded-md border bg-card p-2.5"
                          >
                            <p className="flex flex-wrap items-center gap-2 text-xs font-medium">
                              <FileText className="size-3.5 text-primary" />
                              {docTitles.get(cite.source_document_id) ??
                                `Tài liệu ${cite.source_document_id.slice(0, 8)}…`}
                              <span className="text-muted-foreground">
                                v{cite.source_version}
                              </span>
                              <Badge variant="outline">
                                liên quan{" "}
                                {Math.round(cite.relevance_score * 100)}%
                              </Badge>
                            </p>
                            <p className="mt-1.5 border-l-2 border-primary/40 pl-2 text-xs italic text-muted-foreground">
                              “{cite.quote}”
                            </p>
                          </div>
                        ))}
                      </div>
                    ))}
                    {citeCount === 0 && gate?.passed !== false && (
                      <p className="text-xs text-muted-foreground">
                        Bước này chạy deterministic — không cần truy xuất tri
                        thức.
                      </p>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}
