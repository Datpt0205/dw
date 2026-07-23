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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <ScrollText className="size-6 text-muted-foreground" />
            Nhật ký audit
          </h1>
          <p className="text-sm text-muted-foreground">
            Chuỗi sự kiện append-only trong tenant — kể cả admin cũng không sửa
            được.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Input
            className="w-56"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Lọc theo action / resource…"
          />
          <Button variant="outline" size="icon" onClick={() => void refresh()}>
            <RefreshCw />
          </Button>
        </div>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {events === null && !error && <Skeleton className="h-64 w-full" />}
      {visible?.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Không có sự kiện nào khớp.
        </p>
      )}

      {visible && visible.length > 0 && (
        <Card>
          <CardContent className="pt-5">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Thời điểm</TableHead>
                  <TableHead>Hành động</TableHead>
                  <TableHead>Đối tượng</TableHead>
                  <TableHead>Policy</TableHead>
                  <TableHead>Trace</TableHead>
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
                        {event.action}
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
