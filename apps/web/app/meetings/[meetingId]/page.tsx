"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowRight,
  BadgeCheck,
  ClipboardList,
  ListChecks,
  PauseCircle,
  Play,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import type { Meeting, Run, TimelineEvent } from "@dw/contracts";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@dw/ui";
import { apiClient } from "../../../lib/session";

const ACTION_STATUS: Record<
  string,
  {
    label: string;
    variant: "secondary" | "warning" | "success" | "destructive";
  }
> = {
  proposed: { label: "đề xuất", variant: "secondary" },
  pending_approval: { label: "chờ duyệt", variant: "warning" },
  approved: { label: "đã duyệt", variant: "success" },
  dispatched: { label: "đã giao việc", variant: "success" },
  rejected: { label: "bị từ chối", variant: "destructive" },
};

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
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "lỗi không rõ");
    }
  }, [meetingId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function generate() {
    setBusy(true);
    try {
      await apiClient().generateActions(meetingId);
      toast.success("Đã xử lý cuộc họp — action items đang chờ phê duyệt");
      await refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "lỗi không rõ");
    } finally {
      setBusy(false);
    }
  }

  if (!meeting) {
    return (
      <div className="mx-auto max-w-5xl space-y-4">
        {error ? (
          <Alert variant="destructive">
            <AlertTitle>Không tải được cuộc họp</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : (
          <>
            <Skeleton className="h-8 w-1/2" />
            <Skeleton className="h-48 w-full" />
          </>
        )}
      </div>
    );
  }

  const headline =
    meeting.summary && typeof meeting.summary["headline"] === "string"
      ? (meeting.summary["headline"] as string)
      : null;
  const notProcessed = !headline && meeting.actions.length === 0;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <ClipboardList className="size-6 text-muted-foreground" />
            {meeting.title}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {new Date(meeting.occurred_at).toLocaleString("vi-VN")} ·{" "}
            <Badge variant="secondary">{meeting.status}</Badge>
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={generate}
            disabled={busy || meeting.status === "processing"}
          >
            <Play />
            {busy ? "Đang xử lý…" : "Sinh action items"}
          </Button>
          <Button variant="outline" size="icon" onClick={() => void refresh()}>
            <RefreshCw />
          </Button>
        </div>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}

      {notProcessed && (
        <Alert variant="info">
          <ListChecks className="size-4" />
          <AlertTitle>Transcript đã sẵn sàng</AlertTitle>
          <AlertDescription>
            Bấm <strong>Sinh action items</strong> — máy sẽ tóm tắt, nhặt quyết
            định và công việc kèm người phụ trách.
          </AlertDescription>
        </Alert>
      )}

      {run?.status === "waiting_approval" && (
        <Alert variant="warning">
          <PauseCircle className="size-4" />
          <AlertTitle>Đang chờ phê duyệt</AlertTitle>
          <AlertDescription className="flex items-center justify-between gap-3">
            Action items đã sẵn sàng — chưa có việc nào được giao cho đến khi
            người có quyền duyệt.
            <Button size="sm" variant="outline" asChild>
              <Link href="/approvals">
                Mở Phê duyệt <ArrowRight />
              </Link>
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {run?.status === "completed" && (
        <Alert variant="success">
          <BadgeCheck className="size-4" />
          <AlertTitle>Hoàn tất</AlertTitle>
          <AlertDescription>
            Các việc được duyệt đã dispatch qua connector (có mã tham chiếu bên
            dưới) và ghi vào Nhật ký.
          </AlertDescription>
        </Alert>
      )}

      {headline && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Tóm tắt</CardTitle>
            <CardDescription>{headline}</CardDescription>
          </CardHeader>
          {Array.isArray(meeting.summary?.["key_points"]) && (
            <CardContent>
              <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                {(meeting.summary["key_points"] as string[]).map((point, i) => (
                  <li key={i}>{point}</li>
                ))}
              </ul>
            </CardContent>
          )}
        </Card>
      )}

      {meeting.decisions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Quyết định ({meeting.decisions.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {meeting.decisions.map((decision) => (
              <div
                key={decision.id}
                className="border-l-2 border-primary/40 pl-3"
              >
                <p>{decision.statement}</p>
                {decision.evidence_quote && (
                  <p className="mt-0.5 text-xs italic text-muted-foreground">
                    “{decision.evidence_quote}” —{" "}
                    {decision.decided_by_name ?? "?"}
                  </p>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {meeting.actions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Action items ({meeting.actions.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Công việc</TableHead>
                  <TableHead>Người nhận</TableHead>
                  <TableHead>Hạn</TableHead>
                  <TableHead>Trạng thái</TableHead>
                  <TableHead>Mã giao việc</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {meeting.actions.map((action) => {
                  const status = ACTION_STATUS[action.status] ?? {
                    label: action.status,
                    variant: "secondary" as const,
                  };
                  return (
                    <TableRow key={action.id}>
                      <TableCell>
                        {action.title}
                        {action.approval_reasons.length > 0 && (
                          <span className="mt-1 flex flex-wrap gap-1">
                            {action.approval_reasons.map((reason) => (
                              <Badge key={reason} variant="warning">
                                {reason}
                              </Badge>
                            ))}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        {action.assignee_display_name ?? "—"}
                        {action.assignee_department && (
                          <span className="block text-xs text-muted-foreground">
                            {action.assignee_department}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-xs">
                        {action.due_date
                          ? new Date(action.due_date).toLocaleDateString(
                              "vi-VN",
                            )
                          : "—"}
                        {action.due_date_inferred && (
                          <span className="block text-warning">suy đoán</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant={status.variant}>{status.label}</Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {action.external_url ? (
                          <a
                            className="text-primary underline"
                            href={action.external_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {action.external_ref}
                          </a>
                        ) : (
                          (action.external_ref ?? "—")
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {timeline.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Dòng thời gian run</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="space-y-2 border-l pl-4 text-sm">
              {timeline.map((event, index) => (
                <li key={index} className="relative">
                  <span className="absolute -left-[21px] top-1.5 size-2 rounded-full bg-primary" />
                  <span className="font-mono text-xs text-muted-foreground">
                    {event.occurred_at.slice(11, 19)}
                  </span>{" "}
                  <span className="font-medium">{event.action}</span>
                  {event.policy_decision && (
                    <Badge variant="outline" className="ml-2">
                      {event.policy_decision}
                    </Badge>
                  )}
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
