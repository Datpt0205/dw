"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, ScrollText } from "lucide-react";
import type { AuditEvent } from "@dw/contracts";
import {
  Badge,
  Button,
  Card,
  CardContent,
  Input,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@dw/ui";
import { PageHeading } from "../../components/page-heading";
import { apiClient } from "../../lib/session";

const ACTION_VARIANTS: Record<
  string,
  "secondary" | "warning" | "success" | "default"
> = {
  "run.started": "default",
  "run.waiting_approval": "warning",
  "run.resumed": "default",
  "run.completed": "success",
  "approval.decided": "success",
  "tool.executed": "secondary",
};

const ACTION_LABELS: Record<string, string> = {
  "run.started": "Bắt đầu xử lý",
  "run.waiting_approval": "Chờ phê duyệt",
  "run.resumed": "Tiếp tục xử lý",
  "run.completed": "Hoàn tất xử lý",
  "approval.decided": "Đã có quyết định",
  "tool.executed": "Đã thực hiện tác vụ",
};

export default function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setEvents(await apiClient().listAuditEvents(200));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const visible = events?.filter(
    (event) =>
      !filter ||
      event.action.includes(filter) ||
      event.resource_type.includes(filter) ||
      event.resource_id.includes(filter),
  );

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeading
        eyebrow="Kiểm soát hệ thống"
        icon={ScrollText}
        title="Nhật ký hoạt động"
        description="Lịch sử được lưu liên tục và không thể chỉnh sửa, kể cả bởi quản trị viên."
        actions={
          <>
            <Input
              className="w-56"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Tìm hành động hoặc hồ sơ…"
            />
            <Button
              variant="outline"
              size="icon"
              onClick={() => void refresh()}
            >
              <RefreshCw />
            </Button>
          </>
        }
      />
      {error && <p className="text-sm text-destructive">{error}</p>}
      {events === null && !error && <Skeleton className="h-64 w-full" />}
      {visible?.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Không có sự kiện nào khớp.
        </p>
      )}

      {visible && visible.length > 0 && (
        <Card className="overflow-hidden">
          <CardContent className="pt-5">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Thời điểm</TableHead>
                  <TableHead>Hành động</TableHead>
                  <TableHead>Đối tượng</TableHead>
                  <TableHead>Quy tắc áp dụng</TableHead>
                  <TableHead>Mã đối chiếu</TableHead>
                  <TableHead>Chi tiết</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visible.map((event, index) => (
                  <TableRow key={index} className="align-top">
                    <TableCell className="whitespace-nowrap font-mono text-xs">
                      {new Date(event.occurred_at).toLocaleString("vi-VN")}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={ACTION_VARIANTS[event.action] ?? "secondary"}
                      >
                        {ACTION_LABELS[event.action] ?? "Hoạt động hệ thống"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <span className="text-xs text-muted-foreground">
                        {event.resource_type}
                      </span>
                      <p className="font-mono text-xs">{event.resource_id}</p>
                    </TableCell>
                    <TableCell className="text-xs">
                      {event.policy_decision ?? "—"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {event.trace_id ?? "—"}
                    </TableCell>
                    <TableCell className="max-w-64 truncate text-xs text-muted-foreground">
                      {Object.keys(event.details).length > 0
                        ? JSON.stringify(event.details)
                        : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
