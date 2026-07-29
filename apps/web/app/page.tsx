"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  Banknote,
  BarChart3,
  BookOpen,
  BriefcaseBusiness,
  CheckCircle2,
  Clock3,
  FilePlus2,
  Files,
  FolderKanban,
  ShieldCheck,
} from "lucide-react";
import type { Approval, KnowledgeDocument } from "@dw/contracts";
import type { PreparationCase } from "@dw/api-client";
import { Badge, Button, Card, CardContent, Skeleton } from "@dw/ui";
import { EmptyState } from "../components/empty-state";
import { PageHeading } from "../components/page-heading";
import { StatCard } from "../components/stat-card";
import { useAuth } from "../lib/auth/auth-context";
import { apiClient } from "../lib/session";
import {
  PROCUREMENT_TYPES,
  procurementTypeLabel,
} from "./procurement/dw01/catalog";
import { formatVnd, STATE_BADGE } from "./procurement/dw01/state";

const CLOSED_STATES = new Set(["completed", "intake_rejected", "failed"]);
const ATTENTION_STATES = new Set([
  "draft",
  "waiting_clarification",
  "cp1_pending",
  "cp2_pending",
  "cp3_pending",
  "cp4_ready",
]);

interface DashboardData {
  cases: PreparationCase[];
  approvals: Approval[];
  documents: KnowledgeDocument[];
}

export default function DashboardPage() {
  const { displayName, active, roles, hasScope } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [cases, approvals, documents] = await Promise.all([
        hasScope("tender.read")
          ? apiClient().listPreparationCases()
          : Promise.resolve([]),
        hasScope("approvals.read")
          ? apiClient().listApprovals()
          : Promise.resolve([]),
        hasScope("knowledge.read")
          ? apiClient().listKnowledgeDocuments()
          : Promise.resolve([]),
      ]);
      setData({ cases, approvals, documents });
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Không tải được trang tổng quan",
      );
    }
  }, [hasScope]);

  useEffect(() => {
    void refresh();
  }, [active?.workspaceId, refresh]);

  const metrics = useMemo(() => {
    const cases = data?.cases ?? [];
    const activeCases = cases.filter((item) => !CLOSED_STATES.has(item.state));
    return {
      total: cases.length,
      active: activeCases.length,
      pendingApprovals:
        data?.approvals.filter((item) => item.status === "pending").length ?? 0,
      completed: cases.filter((item) => item.state === "completed").length,
      activeValue: activeCases.reduce(
        (sum, item) => sum + item.estimated_value_minor,
        0,
      ),
      documents: data?.documents.length ?? 0,
    };
  }, [data]);

  const distribution = useMemo(() => {
    const cases = data?.cases ?? [];
    const rows = PROCUREMENT_TYPES.map((type) => ({
      key: type.value,
      label: type.shortLabel,
      count: cases.filter((item) => item.procurement_type === type.value)
        .length,
    })).filter((item) => item.count > 0);
    const max = Math.max(...rows.map((item) => item.count), 1);
    return rows.map((item) => ({
      ...item,
      percentage: (item.count / max) * 100,
    }));
  }, [data]);

  const attentionCases = useMemo(
    () =>
      (data?.cases ?? [])
        .filter((item) => ATTENTION_STATES.has(item.state))
        .slice(0, 5),
    [data],
  );

  const roleLabel = roles.includes("platform_admin")
    ? "Quản trị"
    : roles.includes("approver")
      ? "Quản lý"
      : "Nhân viên";

  return (
    <div className="mx-auto max-w-[1440px] space-y-6">
      <PageHeading
        eyebrow="Tổng quan vận hành"
        icon={BarChart3}
        title={`Chào ${displayName || "bạn"}`}
        description={
          <span className="flex flex-wrap items-center gap-x-2">
            <ShieldCheck className="size-4 text-emerald-600" />
            <span>{active?.workspaceName}</span>
            <span>·</span>
            <span>{roleLabel}</span>
            <span>· Số liệu được cập nhật trực tiếp từ hồ sơ đang quản lý</span>
          </span>
        }
        actions={
          hasScope("tender.write") ? (
            <Button asChild>
              <Link href="/procurement/dw01#new-case">
                <FilePlus2 /> Tạo hồ sơ mới
              </Link>
            </Button>
          ) : undefined
        }
      />

      {error && (
        <div className="rounded-xl border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {data === null && !error ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-32 rounded-2xl" />
          ))}
        </div>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Hồ sơ đang xử lý"
              value={metrics.active}
              hint={`${metrics.total} hồ sơ trong đơn vị`}
              icon={FolderKanban}
              tone="primary"
            />
            <StatCard
              label="Chờ phê duyệt"
              value={metrics.pendingApprovals}
              hint={
                metrics.pendingApprovals > 0
                  ? "Cần quyết định để quy trình tiếp tục"
                  : "Không có yêu cầu tồn đọng"
              }
              icon={Clock3}
              tone={metrics.pendingApprovals > 0 ? "warning" : "success"}
            />
            <StatCard
              label="Giá trị đang xử lý"
              value={
                <span className="text-xl">
                  {formatVnd(metrics.activeValue)}
                </span>
              }
              hint={`${metrics.completed} hồ sơ đã hoàn tất`}
              icon={Banknote}
              tone="neutral"
            />
            <StatCard
              label="Tài liệu tri thức"
              value={metrics.documents}
              hint="Luật, quy chế và biểu mẫu đã sẵn sàng tra cứu"
              icon={BookOpen}
              tone="success"
            />
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.85fr)]">
            <Card>
              <div className="flex items-start justify-between gap-3 border-b px-5 py-4 sm:px-6">
                <div>
                  <h2 className="font-semibold">Hồ sơ cần chú ý</h2>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Ưu tiên theo trạng thái đang chờ con người xử lý
                  </p>
                </div>
                <Link
                  href="/procurement/dw01"
                  className="flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
                >
                  Xem tất cả <ArrowRight className="size-3.5" />
                </Link>
              </div>
              <CardContent className="pt-4">
                {attentionCases.length === 0 ? (
                  <EmptyState
                    icon={CheckCircle2}
                    title="Không có hồ sơ tồn đọng"
                    description="Các hồ sơ hiện tại không ở trạng thái cần xử lý thủ công."
                  />
                ) : (
                  <div className="divide-y">
                    {attentionCases.map((item) => {
                      const state = STATE_BADGE(item.state);
                      return (
                        <Link
                          key={item.id}
                          href={`/procurement/dw01/cases/${item.id}`}
                          className="group flex items-center gap-4 py-3 first:pt-0 last:pb-0"
                        >
                          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-amber-50 text-amber-700">
                            <AlertTriangle className="size-4" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-semibold group-hover:text-primary">
                              {item.title}
                            </span>
                            <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                              {item.source_pr_ref} ·{" "}
                              {procurementTypeLabel(item.procurement_type)} ·{" "}
                              {formatVnd(item.estimated_value_minor)}
                            </span>
                          </span>
                          <Badge variant={state.variant}>{state.label}</Badge>
                          <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                        </Link>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <div className="border-b px-5 py-4 sm:px-6">
                <h2 className="font-semibold">Cơ cấu loại gói thầu</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Phân bổ trên dữ liệu hồ sơ thực tế
                </p>
              </div>
              <CardContent className="pt-5">
                {distribution.length === 0 ? (
                  <EmptyState
                    icon={BriefcaseBusiness}
                    title="Chưa có dữ liệu phân loại"
                    description="Biểu đồ sẽ xuất hiện sau khi hồ sơ đầu tiên được tạo."
                  />
                ) : (
                  <div className="space-y-4">
                    {distribution.map((item) => (
                      <div key={item.key}>
                        <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
                          <span className="font-medium">{item.label}</span>
                          <span className="font-semibold tabular-nums">
                            {item.count}
                          </span>
                        </div>
                        <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                          <div
                            className="h-full rounded-full bg-slate-700 transition-[width]"
                            style={{ width: `${item.percentage}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
            <Card>
              <div className="flex items-center justify-between border-b px-5 py-4 sm:px-6">
                <div>
                  <h2 className="font-semibold">Hồ sơ gần đây</h2>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Tối đa 5 hồ sơ mới nhất
                  </p>
                </div>
                <Badge variant="secondary">{metrics.total} hồ sơ</Badge>
              </div>
              <CardContent className="pt-3">
                {(data?.cases ?? []).length === 0 ? (
                  <EmptyState
                    icon={Files}
                    title="Workspace chưa có hồ sơ"
                    description="Tạo hồ sơ đầu tiên từ PR đã được phê duyệt."
                  />
                ) : (
                  <div className="divide-y">
                    {(data?.cases ?? []).slice(0, 5).map((item) => {
                      const state = STATE_BADGE(item.state);
                      return (
                        <Link
                          key={item.id}
                          href={`/procurement/dw01/cases/${item.id}`}
                          className="group grid gap-2 py-3 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center sm:gap-4"
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-semibold group-hover:text-primary">
                              {item.title}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              {item.source_pr_ref} · {item.owner_name}
                            </span>
                          </span>
                          <span className="text-xs font-medium text-muted-foreground">
                            {procurementTypeLabel(item.procurement_type)}
                          </span>
                          <Badge variant={state.variant}>{state.label}</Badge>
                        </Link>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="border-[#123d61] bg-primary text-white shadow-[0_14px_32px_rgba(11,49,85,0.18)]">
              <CardContent className="pt-6">
                <span className="flex size-10 items-center justify-center rounded-xl bg-white/10">
                  <BadgeCheck className="size-5" />
                </span>
                <h2 className="mt-4 text-lg font-semibold">
                  Phê duyệt có kiểm soát
                </h2>
                <p className="mt-2 text-sm leading-6 text-slate-300">
                  Hệ thống hỗ trợ phân tích và đề xuất, nhưng mọi bước quan
                  trọng vẫn cần người có thẩm quyền xem xét và quyết định.
                </p>
                <div className="mt-5 flex flex-wrap gap-2">
                  {hasScope("approvals.read") && (
                    <Button
                      asChild
                      variant="secondary"
                      className="bg-white text-slate-900 hover:bg-slate-100"
                    >
                      <Link href="/approvals">
                        Xem yêu cầu chờ duyệt <ArrowRight />
                      </Link>
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
