"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  BadgeCheck,
  BookOpen,
  Brain,
  ClipboardList,
  FileSearch,
  Plug,
  ScrollText,
  Sparkles,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";
import type { Approval } from "@dw/contracts";
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
} from "@dw/ui";
import {
  apiClient,
  loadSession,
  loginAs,
  type DevSession,
} from "../../lib/session";

type ApiState = "checking" | "ok" | "down";

function StepBadge({ done, number }: { done: boolean; number: number }) {
  return (
    <span
      className={
        done
          ? "flex size-6 shrink-0 items-center justify-center rounded-full bg-success text-xs font-bold text-white"
          : "flex size-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground"
      }
    >
      {done ? "✓" : number}
    </span>
  );
}

export default function HomePage() {
  const router = useRouter();
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [session, setSession] = useState<DevSession | null>(null);
  const [pending, setPending] = useState<Approval[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const current = loadSession();
    setSession(current);
    try {
      await apiClient().getHealth();
      setApiState("ok");
    } catch {
      setApiState("down");
      return;
    }
    if (current) {
      try {
        const approvals = await apiClient().listApprovals();
        setPending(approvals.filter((a) => a.status === "pending"));
      } catch {
        setPending(null);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function run(label: string, action: () => Promise<void>) {
    setBusy(label);
    try {
      await action();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setBusy(null);
    }
  }

  const loggedIn = session !== null;
  const isApprover = session?.roles?.includes("approver") ?? false;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="rounded-xl border bg-gradient-to-br from-primary/5 via-card to-card p-6">
        <div className="flex items-center gap-2 text-primary">
          <Sparkles className="size-5" />
          <span className="text-xs font-semibold uppercase tracking-wider">
            Digital Worker Platform
          </span>
        </div>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">
          Nhân viên số cho mua sắm &amp; vận hành
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Máy phân tích hồ sơ thầu và biến cuộc họp thành công việc — nhưng mọi
          hành động thật đều dừng lại chờ con người phê duyệt.
        </p>
      </div>

      {apiState === "down" && (
        <Alert variant="destructive">
          <AlertTitle>Không kết nối được API</AlertTitle>
          <AlertDescription>
            Chạy <code>make docker-up</code> hoặc <code>make dev</code> rồi tải
            lại trang.
          </AlertDescription>
        </Alert>
      )}

      {/* Bước 1 — đăng nhập */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-3 text-base">
            <StepBadge done={loggedIn} number={1} />
            Đăng nhập
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-3 text-sm">
          {loggedIn ? (
            <span className="flex items-center gap-2">
              <UserRound className="size-4 text-muted-foreground" />
              <strong>{session.displayName ?? "Phiên thủ công"}</strong>
              {session.tenantName && (
                <span className="text-muted-foreground">
                  · {session.tenantName}
                </span>
              )}
              {session.roles?.map((role) => (
                <Badge key={role} variant="secondary">
                  {role}
                </Badge>
              ))}
            </span>
          ) : (
            <span className="text-muted-foreground">
              <strong className="text-foreground">An</strong> (nhân viên) tạo hồ
              sơ và chạy phân tích ·{" "}
              <strong className="text-foreground">Bình</strong> (trưởng phòng)
              phê duyệt.
            </span>
          )}
          <span className="flex gap-2">
            {!loggedIn && apiState === "ok" && (
              <Button
                onClick={() =>
                  void run("login", async () => {
                    await loginAs("dev|an.nguyen");
                    toast.success("Đã đăng nhập với vai Nguyễn Văn An");
                    await refresh();
                  })
                }
                disabled={busy !== null}
              >
                <UserRound />
                {busy === "login" ? "Đang vào…" : "Vào với vai An"}
              </Button>
            )}
            <Button variant="outline" asChild>
              <Link href="/admin">Chọn người khác</Link>
            </Button>
          </span>
        </CardContent>
      </Card>

      {/* Bước 2 — chạy demo */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-3 text-base">
              <StepBadge done={false} number={2} />
              <FileSearch className="size-4" /> Phân tích hồ sơ thầu
            </CardTitle>
            <CardDescription>
              1 RFQ + 2 chào giá → trích yêu cầu, ma trận tuân thủ kèm trích
              dẫn, chấm điểm deterministic → chờ duyệt.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              className="w-full"
              onClick={() =>
                void run("tender", async () => {
                  const { case_id } = await apiClient().createDemoTenderCase();
                  toast.success(
                    "Đã tạo hồ sơ mẫu — bấm Phân tích ở trang case",
                  );
                  router.push(`/procurement/cases/${case_id}`);
                })
              }
              disabled={!loggedIn || busy !== null}
            >
              {busy === "tender" ? "Đang tạo…" : "Tạo hồ sơ thầu mẫu"}
              <ArrowRight />
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-3 text-base">
              <StepBadge done={false} number={2} />
              <ClipboardList className="size-4" /> Họp → công việc
            </CardTitle>
            <CardDescription>
              Transcript cuộc họp → tóm tắt, quyết định, action item có người
              phụ trách → duyệt xong mới giao việc.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              className="w-full"
              onClick={() =>
                void run("meeting", async () => {
                  const { meeting_id } = await apiClient().createDemoMeeting();
                  toast.success("Đã tạo cuộc họp mẫu — bấm Sinh action items");
                  router.push(`/work-ops/meetings/${meeting_id}`);
                })
              }
              disabled={!loggedIn || busy !== null}
            >
              {busy === "meeting" ? "Đang tạo…" : "Tạo cuộc họp mẫu"}
              <ArrowRight />
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Bước 3 — phê duyệt */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-3 text-base">
            <StepBadge done={false} number={3} />
            <BadgeCheck className="size-4" /> Phê duyệt
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <span className="text-muted-foreground">
            {pending === null
              ? "Máy dừng và chờ con người quyết định trước mọi hành động."
              : pending.length > 0
                ? `Đang có ${pending.length} yêu cầu chờ phê duyệt.`
                : "Chưa có yêu cầu nào chờ — chạy một demo ở bước 2."}
            {loggedIn && !isApprover && (
              <span className="block text-xs">
                Vai hiện tại không duyệt được — sang Đăng nhập chọn{" "}
                <strong className="text-foreground">Trần Thanh Bình</strong>.
              </span>
            )}
          </span>
          <Button variant={pending?.length ? "default" : "outline"} asChild>
            <Link href="/approvals">
              Mở Phê duyệt
              {pending?.length ? (
                <Badge className="ml-1 bg-background text-foreground">
                  {pending.length}
                </Badge>
              ) : null}
            </Link>
          </Button>
        </CardContent>
      </Card>

      {/* Bước 4 — hậu trường */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-3 text-base">
            <StepBadge done={false} number={4} />
            Soi «hậu trường»
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm sm:grid-cols-2">
          {[
            {
              href: "/audit",
              icon: ScrollText,
              label: "Nhật ký",
              hint: "Ai chạy gì, duyệt gì, lúc nào — không sửa được.",
            },
            {
              href: "/knowledge",
              icon: BookOpen,
              label: "Tri thức",
              hint: "Tài liệu đã ingest, luôn cách ly theo tenant.",
            },
            {
              href: "/memory",
              icon: Brain,
              label: "Trí nhớ",
              hint: "Máy chỉ nhớ fact có bằng chứng.",
            },
            {
              href: "/integrations",
              icon: Plug,
              label: "Tích hợp",
              hint: "Tool được phép dùng + chính sách duyệt.",
            },
          ].map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="group flex items-start gap-3 rounded-lg border p-3 transition-colors hover:bg-accent"
            >
              <item.icon className="mt-0.5 size-4 text-muted-foreground group-hover:text-foreground" />
              <span>
                <span className="font-medium">{item.label}</span>
                <span className="block text-xs text-muted-foreground">
                  {item.hint}
                </span>
              </span>
            </Link>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
