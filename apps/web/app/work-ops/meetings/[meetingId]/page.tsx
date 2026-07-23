"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { Meeting, Run, TimelineEvent } from "@dw/contracts";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@dw/ui";
import { apiClient } from "../../../../lib/session";

export default function MeetingDetailPage() {
  const params = useParams<{ meetingId: string }>();
  const meetingId = params.meetingId;
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const client = apiClient();
      const loaded = await client.getMeeting(meetingId);
      setMeeting(loaded);
      if (loaded.last_run_id) {
        setRun(await client.getRun(loaded.last_run_id));
        setTimeline(await client.getRunTimeline(loaded.last_run_id));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    }
  }, [meetingId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      await apiClient().generateActions(meetingId);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setBusy(false);
    }
  }

  if (!meeting) {
    return <p className="text-sm">{error ?? "Đang tải…"}</p>;
  }

  const headline =
    meeting.summary && typeof meeting.summary["headline"] === "string"
      ? (meeting.summary["headline"] as string)
      : null;

  return (
    <div className="max-w-5xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{meeting.title}</h1>
          <p className="text-xs text-slate-500">
            {new Date(meeting.occurred_at).toLocaleString("vi-VN")} · trạng
            thái: <strong>{meeting.status}</strong>
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={generate}
            disabled={busy || meeting.status === "processing"}
          >
            {busy ? "Đang chạy…" : "Sinh action items"}
          </Button>
          <Button variant="outline" onClick={() => void refresh()}>
            Làm mới
          </Button>
        </div>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}

      {run && (
        <Card>
          <CardHeader>
            <CardTitle>Worker run</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>
              <code className="text-xs">{run.id}</code> —{" "}
              <strong>{run.status}</strong> ({run.worker_id}@
              {run.worker_version}, graph {run.graph_version})
            </p>
            {run.status === "waiting_approval" && run.approval_request_id && (
              <p>
                ⏸ Đang chờ phê duyệt —{" "}
                <Link className="text-blue-600 underline" href="/approvals">
                  mở Approval inbox
                </Link>
              </p>
            )}
            {timeline.length > 0 && (
              <ol className="mt-2 space-y-1 border-l border-slate-300 pl-3 text-xs dark:border-slate-700">
                {timeline.map((event, index) => (
                  <li key={index}>
                    <span className="font-mono">
                      {event.occurred_at.slice(11, 19)}
                    </span>{" "}
                    <strong>{event.action}</strong>
                    {event.policy_decision ? ` · ${event.policy_decision}` : ""}
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>
      )}

      {headline && (
        <Card>
          <CardHeader>
            <CardTitle>Tóm tắt</CardTitle>
          </CardHeader>
          <CardContent className="text-sm">
            <p className="font-medium">{headline}</p>
            {Array.isArray(meeting.summary?.["key_points"]) && (
              <ul className="mt-2 list-disc pl-5 text-slate-600 dark:text-slate-400">
                {(meeting.summary["key_points"] as string[]).map((point, i) => (
                  <li key={i}>{point}</li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

      {meeting.decisions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Quyết định ({meeting.decisions.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2 text-sm">
              {meeting.decisions.map((decision) => (
                <li
                  key={decision.id}
                  className="border-l-2 border-slate-300 pl-3"
                >
                  <p>{decision.statement}</p>
                  {decision.evidence_quote && (
                    <p className="text-xs italic text-slate-500">
                      “{decision.evidence_quote}” —{" "}
                      {decision.decided_by_name ?? "?"}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {meeting.actions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Action items ({meeting.actions.length})</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-1 pr-3">Công việc</th>
                  <th className="py-1 pr-3">Người nhận</th>
                  <th className="py-1 pr-3">Hạn</th>
                  <th className="py-1 pr-3">Trạng thái</th>
                  <th className="py-1">External ref</th>
                </tr>
              </thead>
              <tbody>
                {meeting.actions.map((action) => (
                  <tr
                    key={action.id}
                    className="border-t border-slate-200 dark:border-slate-800"
                  >
                    <td className="py-2 pr-3">
                      {action.title}
                      {action.approval_reasons.length > 0 && (
                        <p className="text-xs text-amber-600">
                          {action.approval_reasons.join(", ")}
                        </p>
                      )}
                    </td>
                    <td className="py-2 pr-3">
                      {action.assignee_display_name ?? "—"}
                      {action.assignee_department && (
                        <span className="block text-xs text-slate-500">
                          {action.assignee_department}
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-xs">
                      {action.due_date
                        ? new Date(action.due_date).toLocaleDateString("vi-VN")
                        : "—"}
                      {action.due_date_inferred && (
                        <span className="block text-amber-600">suy đoán</span>
                      )}
                    </td>
                    <td className="py-2 pr-3">
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs dark:bg-slate-800">
                        {action.status}
                      </span>
                    </td>
                    <td className="py-2 font-mono text-xs">
                      {action.external_url ? (
                        <a
                          className="text-blue-600 underline"
                          href={action.external_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {action.external_ref}
                        </a>
                      ) : (
                        (action.external_ref ?? "—")
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
