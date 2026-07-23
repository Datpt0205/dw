"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Bot, Send, X } from "lucide-react";
import { Button, cn, Textarea } from "@dw/ui";
import { apiClient, loadSession } from "../lib/session";

interface ChatMessage {
  role: "user" | "bot";
  text?: string;
  /** Rich bot payload rendered as an analysis card. */
  meetingId?: string;
  headline?: string;
  score?: number;
  wentWell?: string[];
  needsImprovement?: string[];
  recommendations?: string[];
  decisions?: number;
  actions?: { title: string; assignee: string | null }[];
}

const INTRO: ChatMessage = {
  role: "bot",
  text:
    "Xin chào! Dán transcript cuộc họp vào đây (mỗi dòng dạng «Tên: nội dung»), " +
    "tôi sẽ tóm tắt, chấm chất lượng họp, chỉ ra điểm tốt/chưa tốt và đề xuất " +
    "giao việc — giống hệt khi bạn nhắn cho bot Telegram.",
};

/** In-app assistant: same meeting flow as the Telegram bot, no Telegram needed. */
export function AssistantChat() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([INTRO]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, open]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");

    if (!loadSession()) {
      setMessages((prev) => [
        ...prev,
        {
          role: "bot",
          text: "Bạn chưa đăng nhập — vào Trang chủ bấm «Vào với vai An» rồi quay lại nhé.",
        },
      ]);
      return;
    }
    if (text.length < 60 || !text.includes(":")) {
      setMessages((prev) => [
        ...prev,
        {
          role: "bot",
          text:
            "Nội dung chưa giống transcript. Hãy dán hội thoại cuộc họp, " +
            "mỗi dòng dạng «Tên người nói: nội dung…».",
        },
      ]);
      return;
    }

    setBusy(true);
    setMessages((prev) => [
      ...prev,
      { role: "bot", text: "⏳ Đã nhận transcript — đang phân tích cuộc họp…" },
    ]);
    try {
      const client = apiClient();
      const { meeting_id } = await client.createMeeting({
        title: `Họp qua trợ lý ${new Date().toLocaleString("vi-VN")}`,
        occurred_at: new Date().toISOString(),
        transcript_text: text,
      });
      await client.generateActions(meeting_id);
      const meeting = await client.getMeeting(meeting_id);
      const analysis = meeting.analysis;
      setMessages((prev) => [
        ...prev.slice(0, -1), // replace the "đang phân tích" bubble
        {
          role: "bot",
          meetingId: meeting.id,
          headline:
            typeof meeting.summary?.["headline"] === "string"
              ? (meeting.summary["headline"] as string)
              : meeting.title,
          score: analysis?.effectiveness_score,
          wentWell: analysis?.went_well.map((p) => p.point) ?? [],
          needsImprovement:
            analysis?.needs_improvement.map((p) => p.point) ?? [],
          recommendations: analysis?.recommendations ?? [],
          decisions: meeting.decisions.length,
          actions: meeting.actions.map((a) => ({
            title: a.title,
            assignee: a.assignee_display_name,
          })),
        },
      ]);
    } catch (e) {
      setMessages((prev) => [
        ...prev.slice(0, -1),
        {
          role: "bot",
          text: `❌ Không xử lý được: ${e instanceof Error ? e.message : "lỗi không rõ"}`,
        },
      ]);
    } finally {
      setBusy(false);
    }
  }, [input, busy]);

  return (
    <>
      {/* Floating toggle */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="fixed bottom-5 right-5 z-40 flex size-13 items-center justify-center rounded-full bg-primary p-3.5 text-primary-foreground shadow-lg transition-transform hover:scale-105"
        title="Trợ lý Digital Worker"
      >
        {open ? <X className="size-5" /> : <Bot className="size-6" />}
      </button>

      {open && (
        <div className="fixed bottom-20 right-5 z-40 flex h-[540px] w-[400px] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-2xl border bg-background shadow-2xl">
          <div className="flex items-center gap-2 border-b bg-primary px-4 py-3 text-primary-foreground">
            <Bot className="size-5" />
            <div>
              <p className="text-sm font-semibold leading-none">
                Trợ lý Digital Worker
              </p>
              <p className="mt-0.5 text-[11px] opacity-80">
                Cùng bộ não với bot Telegram @AIDigitalWorkBot
              </p>
            </div>
          </div>

          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-3">
            {messages.map((message, i) => (
              <div
                key={i}
                className={cn(
                  "max-w-[85%] rounded-2xl px-3 py-2 text-sm",
                  message.role === "user"
                    ? "ml-auto rounded-br-sm bg-primary text-primary-foreground"
                    : "rounded-bl-sm border bg-card",
                )}
              >
                {message.text && (
                  <p className="whitespace-pre-wrap break-words">
                    {message.text}
                  </p>
                )}
                {message.meetingId && (
                  <div className="space-y-2">
                    <p className="font-semibold">📋 {message.headline}</p>
                    {message.score !== undefined && (
                      <p>
                        ⭐ Chất lượng họp: <b>{message.score}/10</b>
                      </p>
                    )}
                    {message.wentWell && message.wentWell.length > 0 && (
                      <div>
                        <p className="font-medium text-success">✅ Điểm tốt</p>
                        <ul className="ml-4 list-disc text-xs">
                          {message.wentWell.map((p, j) => (
                            <li key={j}>{p}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {message.needsImprovement &&
                      message.needsImprovement.length > 0 && (
                        <div>
                          <p className="font-medium text-warning">
                            ⚠️ Cần cải thiện
                          </p>
                          <ul className="ml-4 list-disc text-xs">
                            {message.needsImprovement.map((p, j) => (
                              <li key={j}>{p}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    {message.recommendations &&
                      message.recommendations.length > 0 && (
                        <div>
                          <p className="font-medium text-primary">
                            💡 Lần sau nên
                          </p>
                          <ul className="ml-4 list-disc text-xs">
                            {message.recommendations.map((p, j) => (
                              <li key={j}>{p}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    <p className="text-xs text-muted-foreground">
                      🗒 {message.decisions} quyết định ·{" "}
                      {message.actions?.length ?? 0} việc cần giao
                    </p>
                    {message.actions?.slice(0, 4).map((action, j) => (
                      <p key={j} className="text-xs">
                        → {action.title} — <b>{action.assignee ?? "chưa rõ"}</b>
                      </p>
                    ))}
                    <div className="flex gap-2 pt-1">
                      <Button size="sm" asChild>
                        <Link href="/approvals">⏸ Phê duyệt</Link>
                      </Button>
                      <Button size="sm" variant="outline" asChild>
                        <Link href={`/meetings/${message.meetingId}`}>
                          Xem chi tiết
                        </Link>
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="flex items-end gap-2 border-t p-3">
            <Textarea
              rows={2}
              className="max-h-28 flex-1 resize-none text-sm"
              placeholder="Dán transcript cuộc họp…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void send();
              }}
            />
            <Button size="icon" onClick={() => void send()} disabled={busy}>
              <Send />
            </Button>
          </div>
        </div>
      )}
    </>
  );
}
