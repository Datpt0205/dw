"use client";

import {
  AlertTriangle,
  CheckCircle2,
  MinusCircle,
  ShieldCheck,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import type { PreparationCase } from "@dw/api-client";
import { Badge, Card, CardContent } from "@dw/ui";
import {
  evaluateCompliance,
  summarize,
  type CheckStatus,
} from "./compliance";

const ICON: Record<CheckStatus, { Icon: LucideIcon; cls: string }> = {
  pass: { Icon: CheckCircle2, cls: "text-emerald-600" },
  warn: { Icon: AlertTriangle, cls: "text-amber-500" },
  fail: { Icon: XCircle, cls: "text-red-600" },
  na: { Icon: MinusCircle, cls: "text-slate-300" },
};

export function ComplianceChecklist({
  caseData,
}: {
  caseData: PreparationCase;
}) {
  const checks = evaluateCompliance(caseData);
  const s = summarize(checks);
  const summaryLabel =
    s.fail > 0
      ? `${s.fail} mục chưa đạt`
      : s.warn > 0
        ? `${s.warn} mục cần lưu ý`
        : "Đạt yêu cầu cơ bản";

  return (
    <Card>
      <div className="flex items-center justify-between gap-3 border-b px-5 py-4 sm:px-6">
        <div className="flex items-center gap-2">
          <ShieldCheck className="size-4 text-primary" />
          <div>
            <h2 className="font-semibold">Bảng kiểm tuân thủ</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Đối chiếu tự động theo cấu hình quy tắc — mang tính tham chiếu
            </p>
          </div>
        </div>
        <Badge variant={s.tone}>{summaryLabel}</Badge>
      </div>
      <CardContent className="pt-4">
        <ul className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
          {checks.map((check) => {
            const { Icon, cls } = ICON[check.status];
            return (
              <li key={check.code} className="flex items-start gap-2.5">
                <Icon className={`mt-0.5 size-4 shrink-0 ${cls}`} />
                <div className="min-w-0">
                  <p
                    className={`text-sm font-medium ${
                      check.status === "na" ? "text-muted-foreground" : ""
                    }`}
                  >
                    {check.label}
                    {check.legalRef && (
                      <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                        · {check.legalRef}
                      </span>
                    )}
                  </p>
                  <p className="text-xs leading-5 text-muted-foreground">
                    {check.detail}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
        <p className="mt-4 border-t pt-3 text-[11px] leading-4 text-muted-foreground">
          Ngưỡng và mốc thời gian là cấu hình demo (theo rule pack). Bộ phận pháp
          chế/đấu thầu cần xác nhận trước khi áp dụng nghiệp vụ thật.
        </p>
      </CardContent>
    </Card>
  );
}
