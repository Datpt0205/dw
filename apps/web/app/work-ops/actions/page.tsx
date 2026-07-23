"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { ActionItem, Meeting } from "@dw/contracts";
import { apiClient } from "../../../lib/session";

interface ActionWithMeeting extends ActionItem {
  meetingId: string;
  meetingTitle: string;
}

export default function ActionsPage() {
  const [actions, setActions] = useState<ActionWithMeeting[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const client = apiClient();
    client
      .listMeetings()
      .then(async (meetings: Meeting[]) => {
        const detailed = await Promise.all(
          meetings.map((meeting) => client.getMeeting(meeting.id)),
        );
        setActions(
          detailed.flatMap((meeting) =>
            meeting.actions.map((action) => ({
              ...action,
              meetingId: meeting.id,
              meetingTitle: meeting.title,
            })),
          ),
        );
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "lỗi không rõ"),
      );
  }, []);

  return (
    <div className="max-w-4xl space-y-6">
      <h1 className="text-2xl font-bold">Action items</h1>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {actions === null && !error && <p className="text-sm">Đang tải…</p>}
      {actions?.length === 0 && (
        <p className="text-sm">Chưa có action item nào.</p>
      )}
      <div className="space-y-2">
        {actions?.map((action) => (
          <div
            key={action.id}
            className="rounded-lg border border-slate-200 bg-white p-3 text-sm dark:border-slate-800 dark:bg-slate-900"
          >
            <div className="flex items-center justify-between">
              <span className="font-medium">{action.title}</span>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs dark:bg-slate-800">
                {action.status}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              {action.assignee_display_name ?? "chưa có người nhận"} · từ{" "}
              <Link
                className="text-blue-600 underline"
                href={`/work-ops/meetings/${action.meetingId}`}
              >
                {action.meetingTitle}
              </Link>
              {action.external_ref ? ` · ${action.external_ref}` : ""}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
