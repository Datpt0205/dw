import type { PreparationCase } from "@dw/api-client";

/**
 * Advisory compliance checklist for a DW01 case (đèn xanh/đỏ). Deterministic —
 * derived from the case + its artifacts, mirroring the thresholds in
 * configs/policies/dw01/procurement_rules_v1.yaml. This is a *presentation* aid;
 * the binding gates still live in the backend workflow.
 *
 * NOTE: thresholds are demo placeholders (like the rule pack). For production
 * these should be served by the backend so there is a single source of truth.
 */

export type CheckStatus = "pass" | "warn" | "fail" | "na";

export interface ComplianceCheck {
  code: string;
  label: string;
  status: CheckStatus;
  detail: string;
  legalRef?: string;
}

const METHOD_MAX: Record<string, number | null> = {
  direct_purchase: 100_000_000,
  rfq: 1_000_000_000,
  open_tender: null,
};
const METHOD_LABEL: Record<string, string> = {
  direct_purchase: "Mua sắm trực tiếp",
  rfq: "Chào giá cạnh tranh",
  open_tender: "Đấu thầu rộng rãi",
};
const LEGAL_REVIEW_ABOVE = 500_000_000;
const BID_SECURITY_METHODS = new Set(["rfq", "open_tender"]);
// Indicative minimum solicitation window (days) before bid closing.
const MIN_SOLICITATION_DAYS: Record<string, number> = {
  rfq: 7,
  open_tender: 22,
};

function content(
  c: PreparationCase,
  type: string,
): Record<string, unknown> | null {
  const a = c.artifacts.find((x) => x.artifact_type === type);
  return a ? (a.content as Record<string, unknown>) : null;
}

function na(code: string, label: string, detail: string): ComplianceCheck {
  return { code, label, status: "na", detail };
}

export function evaluateCompliance(c: PreparationCase): ComplianceCheck[] {
  const approach = content(c, "procurement_approach");
  const criteria = content(c, "evaluation_criteria");
  const solicitation = content(c, "solicitation_package");
  const checks: ComplianceCheck[] = [];

  checks.push({
    code: "PR",
    label: "Có PR đã phê duyệt",
    status: c.source_pr_ref ? "pass" : "fail",
    detail: c.source_pr_ref
      ? `Tham chiếu ${c.source_pr_ref}`
      : "Thiếu PR nguồn đã được phê duyệt",
    legalRef: "Điều kiện đầu vào",
  });

  if (c.method_key) {
    const max = METHOD_MAX[c.method_key] ?? null;
    const ok = max === null || c.estimated_value_minor <= max;
    checks.push({
      code: "METHOD",
      label: "Hình thức phù hợp giá trị gói",
      status: ok ? "pass" : "warn",
      detail: ok
        ? `${METHOD_LABEL[c.method_key] ?? c.method_key} — trong ngưỡng giá trị`
        : `Giá trị vượt ngưỡng của ${METHOD_LABEL[c.method_key] ?? c.method_key}`,
      legalRef: "Hình thức lựa chọn nhà thầu",
    });
  } else {
    checks.push(
      na(
        "METHOD",
        "Hình thức phù hợp giá trị gói",
        "Chưa xác định hình thức (chạy tới bước phương án)",
      ),
    );
  }

  if (approach) {
    const planned = Number(approach["supplier_count_planned"] ?? 0);
    const min = Number(approach["min_suppliers"] ?? 0);
    checks.push({
      code: "SUPPLIERS",
      label: "Đủ số nhà cung cấp tối thiểu",
      status: planned >= min ? "pass" : "warn",
      detail: `Dự kiến ${planned} / tối thiểu ${min}`,
    });
  } else {
    checks.push(
      na("SUPPLIERS", "Đủ số nhà cung cấp tối thiểu", "Chưa có phương án"),
    );
  }

  if (c.method_key && BID_SECURITY_METHODS.has(c.method_key)) {
    const declared = approach !== null && "bid_security" in approach;
    checks.push({
      code: "BID_SECURITY",
      label: "Bảo đảm dự thầu",
      status: declared ? "pass" : "warn",
      detail: declared
        ? "Đã khai báo mức bảo đảm dự thầu"
        : "Chưa khai báo bảo đảm dự thầu (thường 1–3% giá gói)",
      legalRef: "Bảo đảm dự thầu",
    });
  }

  const minDays = c.method_key ? MIN_SOLICITATION_DAYS[c.method_key] : undefined;
  if (solicitation && minDays !== undefined) {
    const submission = (solicitation["submission"] ?? {}) as Record<
      string,
      unknown
    >;
    const days = Number(submission["deadline_offset_days"] ?? 0);
    checks.push({
      code: "TIMELINE",
      label: "Thời gian chuẩn bị hồ sơ dự thầu",
      status: days >= minDays ? "pass" : "warn",
      detail: `${days} ngày / tối thiểu ~${minDays} ngày`,
      legalRef: "Thời gian trong đấu thầu",
    });
  }

  if (criteria) {
    const total = Number(criteria["weighted_total"] ?? 0);
    checks.push({
      code: "WEIGHTS",
      label: "Tổng trọng số tiêu chí = 100",
      status: total === 100 ? "pass" : "fail",
      detail: `Hiện tại: ${total}`,
    });
    const hasMandatory = Boolean(criteria["has_mandatory"]);
    checks.push({
      code: "MANDATORY",
      label: "Có tiêu chí tiên quyết (đạt/không đạt)",
      status: hasMandatory ? "pass" : "fail",
      detail: hasMandatory ? "Đã có tiêu chí bắt buộc" : "Thiếu tiêu chí tiên quyết",
    });
  } else {
    checks.push(na("WEIGHTS", "Tổng trọng số tiêu chí = 100", "Chưa có tiêu chí"));
  }

  if (c.estimated_value_minor > LEGAL_REVIEW_ABOVE) {
    checks.push({
      code: "LEGAL_REVIEW",
      label: "Thẩm định trước khi phê duyệt",
      status: "warn",
      detail: "Giá trị lớn — nên có bước thẩm định pháp lý/tài chính",
      legalRef: "Thẩm định",
    });
  }

  return checks;
}

export interface ComplianceSummary {
  fail: number;
  warn: number;
  pass: number;
  na: number;
  tone: "success" | "warning" | "destructive";
}

export function summarize(checks: ComplianceCheck[]): ComplianceSummary {
  const fail = checks.filter((x) => x.status === "fail").length;
  const warn = checks.filter((x) => x.status === "warn").length;
  const pass = checks.filter((x) => x.status === "pass").length;
  const na = checks.filter((x) => x.status === "na").length;
  const tone = fail > 0 ? "destructive" : warn > 0 ? "warning" : "success";
  return { fail, warn, pass, na, tone };
}
