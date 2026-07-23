"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { Meeting } from "@dw/contracts";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@dw/ui";
import { apiClient } from "../../../lib/session";

export default function MeetingsPage() {
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [transcript, setTranscript] = useState("");
  const [creating, setCreating] = useState(false);

  const refresh = useCallback(() => {
    apiClient()
      .listMeetings()
      .then(setMeetings)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "lỗi không rõ"),
      );
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function create() {
    setCreating(true);
    setError(null);
    try {
      const { meeting_id } = await apiClient().createMeeting({
        title,
        occurred_at: new Date().toISOString(),
        transcript_text: transcript,
      });
      setTitle("");
      setTranscript("");
      refresh();
      window.location.href = `/work-ops/meetings/${meeting_id}`;
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setCreating(false);
    }
  }

  async function createDemo() {
    setCreating(true);
    setError(null);
    try {
      const { meeting_id } = await apiClient().createDemoMeeting();
      window.location.href = `/work-ops/meetings/${meeting_id}`;
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Cuộc họp</h1>
        <Button onClick={() => void createDemo()} disabled={creating}>
          {creating ? "Đang tạo…" : "⚡ Tạo cuộc họp mẫu"}
        </Button>
      </div>
      {error && (
        <p className="text-sm text-red-600">
          {error} — kiểm tra phiên ở trang Admin.
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Tạo cuộc họp mới từ transcript</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <input
            className="w-full rounded-md border border-slate-300 p-2 text-sm dark:border-slate-700 dark:bg-slate-950"
            placeholder="Tiêu đề cuộc họp"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <textarea
            className="w-full rounded-md border border-slate-300 p-2 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
            rows={8}
            placeholder={
              "Dán transcript theo dạng:\nTên người nói: nội dung..."
            }
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
          />
          <Button
            onClick={create}
            disabled={creating || !title.trim() || !transcript.trim()}
          >
            {creating ? "Đang tạo…" : "Tạo cuộc họp"}
          </Button>
        </CardContent>
      </Card>

      <div className="space-y-3">
        {meetings === null && !error && <p className="text-sm">Đang tải…</p>}
        {meetings?.length === 0 && (
          <p className="text-sm">Chưa có cuộc họp nào.</p>
        )}
        {meetings?.map((meeting) => (
          <Link
            key={meeting.id}
            href={`/work-ops/meetings/${meeting.id}`}
            className="block rounded-lg border border-slate-200 bg-white p-4 hover:border-slate-400 dark:border-slate-800 dark:bg-slate-900"
          >
            <div className="flex items-center justify-between">
              <span className="font-medium">{meeting.title}</span>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs dark:bg-slate-800">
                {meeting.status}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              {new Date(meeting.occurred_at).toLocaleString("vi-VN")}
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}
