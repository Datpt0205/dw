"use client";

import { useCallback, useEffect, useState } from "react";
import { MessageSquare } from "lucide-react";
import type { ChannelLinkStatus } from "@dw/contracts";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "@dw/ui";
import { apiClient } from "../lib/session";

const CHANNEL = "zalo";

/**
 * Connect a Zalo account to the signed-in identity.
 *
 * The code is shown, never sent anywhere: this page already knows who you are,
 * and the chat side proves only which account was holding it. It is short-lived
 * on purpose, so the panel says when it dies rather than leaving it on screen
 * looking valid.
 */
export function ZaloLinkCard() {
  const [status, setStatus] = useState<ChannelLinkStatus | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<Date | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const links = await apiClient().listChannelLinks();
      setStatus(links.find((l) => l.channel === CHANNEL) ?? null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function getCode() {
    setBusy(true);
    setError(null);
    try {
      const issued = await apiClient().createChannelLinkCode(CHANNEL);
      setCode(issued.code);
      setExpiresAt(new Date(issued.expires_at));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setBusy(false);
    }
  }

  async function unlink() {
    setBusy(true);
    setError(null);
    try {
      await apiClient().unlinkChannel(CHANNEL);
      setCode(null);
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setBusy(false);
    }
  }

  const linked = status?.linked ?? false;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2">
          <MessageSquare className="size-4" aria-hidden />
          Kết nối Zalo
        </CardTitle>
        <Badge variant={linked ? "default" : "secondary"}>
          {linked ? "Đã liên kết" : "Chưa liên kết"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <p className="text-muted-foreground">
          Liên kết tài khoản Zalo để nhắn việc và nhận thẻ phê duyệt ngay trên
          Zalo. Chỉ tài khoản bạn tự liên kết mới nhận được; huỷ lúc nào cũng
          được.
        </p>

        {error && <p className="text-red-600">{error}</p>}

        {linked ? (
          <div className="space-y-3">
            <p>
              Đang liên kết với tài khoản Zalo{" "}
              <code className="rounded bg-muted px-1.5 py-0.5">
                {status?.account}
              </code>
            </p>
            <Button variant="outline" onClick={unlink} disabled={busy}>
              Huỷ liên kết
            </Button>
            <p className="text-xs text-muted-foreground">
              Cũng có thể nhắn <code>/stop</code> cho bot để tự huỷ.
            </p>
          </div>
        ) : code ? (
          <div className="space-y-2">
            <p>Mở bot DW trên Zalo và nhắn đúng mã dưới đây:</p>
            <code className="block rounded border bg-muted px-3 py-2 text-lg tracking-widest">
              {code}
            </code>
            <p className="text-xs text-muted-foreground">
              {expiresAt
                ? `Hết hạn lúc ${expiresAt.toLocaleTimeString("vi-VN")}. `
                : ""}
              Nhắn xong bot trả lời “Đã liên kết”. Bấm lại nút bên dưới nếu cần
              mã mới.
            </p>
            <Button variant="outline" onClick={getCode} disabled={busy}>
              Lấy mã khác
            </Button>
          </div>
        ) : (
          <Button onClick={getCode} disabled={busy}>
            {busy ? "Đang lấy mã…" : "Kết nối Zalo"}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
