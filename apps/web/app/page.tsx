"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  ClipboardList,
  FileSearch,
  LogIn,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";
import type { DemoUser } from "@dw/contracts";
import { Badge, Button, Card, CardContent } from "@dw/ui";
import {
  apiClient,
  clearSession,
  loadSession,
  loginAs,
  type DevSession,
} from "../lib/session";

const ROLE_LABELS: Record<string, string> = {
  member: "Nhân viên",
  approver: "Phê duyệt",
  platform_admin: "Quản trị",
};

export default function LandingPage() {
  const [session, setSession] = useState<DevSession | null>(null);
  const [users, setUsers] = useState<DemoUser[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [apiDown, setApiDown] = useState(false);

  const refresh = useCallback(async () => {
    setSession(loadSession());
    try {
      await apiClient().getHealth();
      setApiDown(false);
      setUsers(await apiClient().listDemoUsers());
    } catch {
      setApiDown(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleLogin(user: DemoUser) {
    setBusy(user.subject);
    try {
      setSession(await loginAs(user.subject));
      toast.success(`Đã đăng nhập: ${user.display_name}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Digital Worker Platform
        </h1>
        <p className="mt-1 max-w-xl text-sm text-muted-foreground">
          Máy phân tích và đề xuất — con người luôn phê duyệt trước khi bất kỳ
          hành động thật nào xảy ra.
        </p>
      </div>

      {apiDown && (
        <p className="text-center text-sm text-destructive">
          Không kết nối được API — chạy <code>make docker-up</code> rồi tải lại.
        </p>
      )}

      {/* Đăng nhập */}
      <Card>
        <CardContent className="pt-5">
          {session ? (
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
              <span className="flex items-center gap-2">
                <ShieldCheck className="size-4 text-success" />
                Đang đăng nhập:{" "}
                <strong>{session.displayName ?? "Phiên thủ công"}</strong>
                {session.roles?.map((role) => (
                  <Badge key={role} variant="secondary">
                    {ROLE_LABELS[role] ?? role}
                  </Badge>
                ))}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  clearSession();
                  setSession(null);
                }}
              >
                Đăng xuất
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-center text-sm font-medium">
                Đăng nhập nhanh bằng nhân vật demo
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {users?.map((user) => (
                  <Button
                    key={user.subject}
                    variant="outline"
                    size="sm"
                    onClick={() => void handleLogin(user)}
                    disabled={busy !== null}
                  >
                    <LogIn />
                    {busy === user.subject ? "Đang vào…" : user.display_name}
                    <span className="text-xs text-muted-foreground">
                      ({user.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ")})
                    </span>
                  </Button>
                ))}
                {users === null && !apiDown && (
                  <span className="text-sm text-muted-foreground">
                    Đang tải danh sách…
                  </span>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Hai module */}
      <div className="grid gap-5 md:grid-cols-2">
        <Link href="/tender" className="group">
          <Card className="h-full transition-all group-hover:-translate-y-0.5 group-hover:shadow-md">
            <CardContent className="pt-6">
              <span className="flex size-11 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                <FileSearch className="size-6" />
              </span>
              <h2 className="mt-4 flex items-center gap-2 text-lg font-semibold">
                Phân tích đấu thầu
                <ArrowRight className="size-4 opacity-0 transition-opacity group-hover:opacity-100" />
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Hồ sơ RFQ + chào giá → ma trận tuân thủ kèm trích dẫn, chấm điểm
                deterministic, đề xuất chờ phê duyệt.
              </p>
            </CardContent>
          </Card>
        </Link>

        <Link href="/meetings" className="group">
          <Card className="h-full transition-all group-hover:-translate-y-0.5 group-hover:shadow-md">
            <CardContent className="pt-6">
              <span className="flex size-11 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600">
                <ClipboardList className="size-6" />
              </span>
              <h2 className="mt-4 flex items-center gap-2 text-lg font-semibold">
                Quản lý cuộc họp
                <ArrowRight className="size-4 opacity-0 transition-opacity group-hover:opacity-100" />
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Transcript → tóm tắt, quyết định, action item có người phụ trách
                — duyệt xong mới giao việc.
              </p>
            </CardContent>
          </Card>
        </Link>
      </div>

      <p className="text-xs text-muted-foreground">
        Trang hệ thống:{" "}
        <Link className="underline hover:text-foreground" href="/audit">
          Nhật ký
        </Link>{" "}
        ·{" "}
        <Link className="underline hover:text-foreground" href="/knowledge">
          Tri thức
        </Link>{" "}
        ·{" "}
        <Link className="underline hover:text-foreground" href="/memory">
          Trí nhớ
        </Link>{" "}
        ·{" "}
        <Link className="underline hover:text-foreground" href="/integrations">
          Tích hợp
        </Link>{" "}
        ·{" "}
        <Link className="underline hover:text-foreground" href="/admin">
          Admin
        </Link>
      </p>
    </div>
  );
}
