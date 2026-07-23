"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, Plus, Zap } from "lucide-react";
import { toast } from "sonner";
import type { Meeting } from "@dw/contracts";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Skeleton,
  Textarea,
} from "@dw/ui";
import { apiClient, canCreate, loadSession } from "../../lib/session";

export default function MeetingsPage() {
  const router = useRouter();
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [transcript, setTranscript] = useState("");
  const [creating, setCreating] = useState(false);

  const allowed = canCreate(loadSession());

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

  async function createDemo() {
    setCreating(true);
    try {
      const { meeting_id } = await apiClient().createDemoMeeting();
      toast.success("Đã tạo cuộc họp mẫu");
      router.push(`/meetings/${meeting_id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "lỗi không rõ");
      setCreating(false);
    }
  }

  async function create() {
    setCreating(true);
    try {
      const { meeting_id } = await apiClient().createMeeting({
        title,
        occurred_at: new Date().toISOString(),
        transcript_text: transcript,
      });
      router.push(`/meetings/${meeting_id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "lỗi không rõ");
      setCreating(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Cuộc họp</h1>
          <p className="text-sm text-muted-foreground">
            Từ transcript đến action item được phê duyệt và giao việc.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={() => void createDemo()}
            disabled={creating || !allowed}
          >
            <Zap />
            {creating ? "Đang tạo…" : "Tạo cuộc họp mẫu"}
          </Button>
          <Button
            variant="outline"
            onClick={() => setShowForm((v) => !v)}
            disabled={!allowed}
          >
            <Plus /> Tự nhập
          </Button>
        </div>
      </div>
      {!allowed && (
        <p className="rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
          Vai «Người phê duyệt» chỉ duyệt, không tạo cuộc họp — sang Đăng nhập
          chọn <strong>Nguyễn Văn An (Nhân viên)</strong> để tạo.
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}

      {showForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Tạo cuộc họp từ transcript
            </CardTitle>
            <CardDescription>
              Định dạng mỗi dòng: <code>Tên người nói: nội dung…</code>
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input
              placeholder="Tiêu đề cuộc họp"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <Textarea
              className="font-mono text-xs"
              rows={8}
              placeholder={"Nguyễn Văn An: Chào cả nhóm…\nTrần Bình: …"}
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
      )}

      <div className="space-y-2">
        {meetings === null && !error && <Skeleton className="h-32 w-full" />}
        {meetings?.length === 0 && (
          <Card>
            <CardContent className="pt-5 text-sm text-muted-foreground">
              Chưa có cuộc họp nào — bấm <strong>Tạo cuộc họp mẫu</strong> để
              bắt đầu.
            </CardContent>
          </Card>
        )}
        {meetings?.map((meeting) => (
          <Link
            key={meeting.id}
            href={`/meetings/${meeting.id}`}
            className="group flex items-center justify-between rounded-xl border bg-card p-4 shadow-sm transition-colors hover:bg-accent"
          >
            <div>
              <span className="font-medium">{meeting.title}</span>
              <p className="text-xs text-muted-foreground">
                {new Date(meeting.occurred_at).toLocaleString("vi-VN")}
              </p>
            </div>
            <span className="flex items-center gap-2">
              <Badge variant="secondary">{meeting.status}</Badge>
              <ChevronRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
