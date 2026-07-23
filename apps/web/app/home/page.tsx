"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Approval } from "@dw/contracts";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@dw/ui";
import {
  apiClient,
  loadSession,
  loginAs,
  type DevSession,
} from "../../lib/session";

type ApiState = "checking" | "ok" | "down";

export default function HomePage() {
  const router = useRouter();
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [session, setSession] = useState<DevSession | null>(null);
  const [pending, setPending] = useState<Approval[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setBusy(null);
    }
  }

  const loggedIn = session !== null;
  const isApprover = session?.roles?.includes("approver") ?? false;

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Digital Worker Platform</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Hai «nhân viên số»: phân tích hồ sơ thầu và biến cuộc họp thành công
          việc — luôn có con người phê duyệt trước mọi hành động thật.
        </p>
      </div>

      {apiState === "down" && (
        <Card>
          <CardContent className="pt-4 text-sm text-red-600">
            Không kết nối được API — chạy <code>make docker-up</code> hoặc{" "}
            <code>make dev</code> rồi tải lại trang.
          </CardContent>
        </Card>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {/* ---------------------------------------------------------- Bước 1 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {loggedIn ? "✅" : "1️⃣"} Đăng nhập
          </CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-between text-sm">
          {loggedIn ? (
            <span>
              Xin chào <strong>{session.displayName ?? "bạn"}</strong>
              {session.tenantName && (
                <span className="text-slate-500"> · {session.tenantName}</span>
              )}{" "}
              {session.roles?.map((r) => (
                <span
                  key={r}
                  className="ml-1 rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                >
                  {r}
                </span>
              ))}
            </span>
          ) : (
            <span>
              Vào nhanh bằng nhân vật demo — <strong>An</strong> (nhân viên) tạo
              hồ sơ, <strong>Bình</strong> (trưởng phòng) phê duyệt.
            </span>
          )}
          <span className="flex shrink-0 gap-2">
            {!loggedIn && apiState === "ok" && (
              <Button
                onClick={() =>
                  void run("login", async () => {
                    await loginAs("dev|an.nguyen");
                    await refresh();
                  })
                }
                disabled={busy !== null}
              >
                {busy === "login" ? "Đang vào…" : "Vào với vai An (nhân viên)"}
              </Button>
            )}
            <Link href="/admin">
              <Button variant="outline">Chọn người khác</Button>
            </Link>
          </span>
        </CardContent>
      </Card>

      {/* ---------------------------------------------------------- Bước 2 */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">2️⃣ Demo Phân tích thầu</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p className="text-slate-600 dark:text-slate-400">
              Tạo hồ sơ mẫu (1 RFQ + 2 chào giá) → máy trích yêu cầu, đối chiếu
              từng nhà cung cấp kèm trích dẫn, chấm điểm deterministic → bạn phê
              duyệt đề xuất.
            </p>
            <Button
              onClick={() =>
                void run("tender", async () => {
                  const { case_id } = await apiClient().createDemoTenderCase();
                  router.push(`/procurement/cases/${case_id}`);
                })
              }
              disabled={!loggedIn || busy !== null}
            >
              {busy === "tender" ? "Đang tạo…" : "Tạo hồ sơ thầu mẫu"}
            </Button>
            {!loggedIn && (
              <p className="text-xs text-slate-500">Cần đăng nhập trước.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">2️⃣ Demo Họp → Việc</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p className="text-slate-600 dark:text-slate-400">
              Tạo cuộc họp mẫu từ transcript → máy tóm tắt, nhặt quyết định và
              action item, tìm người phụ trách → duyệt xong mới giao việc.
            </p>
            <Button
              onClick={() =>
                void run("meeting", async () => {
                  const { meeting_id } = await apiClient().createDemoMeeting();
                  router.push(`/work-ops/meetings/${meeting_id}`);
                })
              }
              disabled={!loggedIn || busy !== null}
            >
              {busy === "meeting" ? "Đang tạo…" : "Tạo cuộc họp mẫu"}
            </Button>
            {!loggedIn && (
              <p className="text-xs text-slate-500">Cần đăng nhập trước.</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ---------------------------------------------------------- Bước 3 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">3️⃣ Phê duyệt</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-between text-sm">
          <span>
            {pending === null
              ? "Máy dừng lại và chờ con người quyết định trước mọi hành động."
              : pending.length > 0
                ? `Đang có ${pending.length} yêu cầu chờ phê duyệt.`
                : "Chưa có yêu cầu nào chờ — chạy một demo ở bước 2 trước."}
            {loggedIn && !isApprover && (
              <span className="block text-xs text-slate-500">
                Vai hiện tại không có quyền duyệt — sang Admin đổi sang{" "}
                <strong>Trần Thanh Bình</strong>.
              </span>
            )}
          </span>
          <Link href="/approvals">
            <Button variant="outline">
              Mở Approvals{pending?.length ? ` (${pending.length})` : ""}
            </Button>
          </Link>
        </CardContent>
      </Card>

      {/* ---------------------------------------------------------- Bước 4 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">4️⃣ Soi «hậu trường»</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm md:grid-cols-2">
          <Link
            className="rounded-md border border-slate-200 p-3 hover:border-slate-400 dark:border-slate-800"
            href="/audit"
          >
            <strong>Audit</strong>
            <p className="text-xs text-slate-500">
              Chuỗi sự kiện bất biến: ai chạy gì, duyệt gì, lúc nào.
            </p>
          </Link>
          <Link
            className="rounded-md border border-slate-200 p-3 hover:border-slate-400 dark:border-slate-800"
            href="/knowledge"
          >
            <strong>Knowledge</strong>
            <p className="text-xs text-slate-500">
              Tài liệu đã ingest vào chỉ mục tri thức (luôn cách ly theo
              tenant).
            </p>
          </Link>
          <Link
            className="rounded-md border border-slate-200 p-3 hover:border-slate-400 dark:border-slate-800"
            href="/memory"
          >
            <strong>Memory</strong>
            <p className="text-xs text-slate-500">
              Điều máy «nhớ» lâu dài — chỉ fact có bằng chứng mới được ghi.
            </p>
          </Link>
          <Link
            className="rounded-md border border-slate-200 p-3 hover:border-slate-400 dark:border-slate-800"
            href="/integrations"
          >
            <strong>Integrations</strong>
            <p className="text-xs text-slate-500">
              Tool được phép dùng + chính sách phê duyệt của từng tool.
            </p>
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
