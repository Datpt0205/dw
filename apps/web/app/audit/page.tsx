"use client";

import { useCallback, useEffect, useState } from "react";
import type { AuditEvent } from "@dw/contracts";
import { Button } from "@dw/ui";
import { apiClient } from "../../lib/session";

const ACTION_COLORS: Record<string, string> = {
  "run.started": "text-blue-600 dark:text-blue-400",
  "run.waiting_approval": "text-amber-600",
  "run.resumed": "text-blue-600 dark:text-blue-400",
  "run.completed": "text-green-700 dark:text-green-400",
  "approval.decided": "text-purple-600 dark:text-purple-400",
  "tool.executed": "text-slate-700 dark:text-slate-300",
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
    <div className="max-w-6xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Audit trail</h1>
          <p className="text-xs text-slate-500">
            Chuỗi sự kiện bất biến (append-only) trong tenant hiện tại
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="lọc theo action / resource…"
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
          />
          <Button variant="outline" onClick={() => void refresh()}>
            Làm mới
          </Button>
        </div>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {events === null && !error && <p className="text-sm">Đang tải…</p>}
      {visible?.length === 0 && (
        <p className="text-sm">Không có sự kiện audit nào khớp.</p>
      )}
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Thời điểm</th>
              <th className="px-3 py-2">Action</th>
              <th className="px-3 py-2">Resource</th>
              <th className="px-3 py-2">Policy</th>
              <th className="px-3 py-2">Trace</th>
              <th className="px-3 py-2">Chi tiết</th>
            </tr>
          </thead>
          <tbody>
            {visible?.map((event, index) => (
              <tr
                key={index}
                className="border-t border-slate-100 align-top dark:border-slate-800"
              >
                <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">
                  {new Date(event.occurred_at).toLocaleString("vi-VN")}
                </td>
                <td
                  className={`px-3 py-2 font-medium ${ACTION_COLORS[event.action] ?? ""}`}
                >
                  {event.action}
                </td>
                <td className="px-3 py-2">
                  <span className="text-xs text-slate-500">
                    {event.resource_type}
                  </span>
                  <p className="font-mono text-xs">{event.resource_id}</p>
                </td>
                <td className="px-3 py-2 text-xs">
                  {event.policy_decision ?? "—"}
                </td>
                <td className="px-3 py-2 font-mono text-xs">
                  {event.trace_id ?? "—"}
                </td>
                <td className="px-3 py-2 text-xs text-slate-500">
                  {Object.keys(event.details).length > 0
                    ? JSON.stringify(event.details)
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
