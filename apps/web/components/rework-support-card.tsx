"use client";

import { useCallback, useEffect, useState } from "react";
import { HeartHandshake } from "lucide-react";
import { toast } from "sonner";
import type { ReworkSupport } from "@dw/api-client";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Textarea,
} from "@dw/ui";
import { apiClient } from "../lib/session";
import { DW01_READONLY } from "../lib/readonly";

/**
 * Shown to a requester whose recent cases have been coming back.
 *
 * Every sentence on this card comes from the server. None of it is assembled
 * here on purpose: the phrasing is a tested requirement — the feature must
 * never read as an accusation — and a rule enforced in one module cannot be
 * enforced by a component that writes its own copy.
 *
 * It also fetches separately from the case rather than riding along on the
 * case payload, so that opening a case page never waits on this and a slow or
 * failing tally leaves the rest of the page untouched.
 */
export function ReworkSupportCard({
  caseId,
  onSubmitted,
}: {
  caseId: string;
  onSubmitted?: () => void;
}) {
  const [support, setSupport] = useState<ReworkSupport | null>(null);
  const [context, setContext] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [ask, setAsk] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  const refresh = useCallback(() => {
    apiClient()
      .getMyReworkSupport()
      // Fail quiet, exactly as the server does. An outage here must never
      // become a scary message on somebody's screen.
      .then(setSupport)
      .catch(() => setSupport(null));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // "Could not compute" is not "all clear" — say nothing rather than imply
  // a clean slate. Same reason the server keeps the two apart.
  if (!support || !support.available || support.level === "none") return null;

  const blocked = support.level === "block";
  const tooShort = context.trim().length < support.explanation_min_chars;

  async function submit() {
    setBusy(true);
    try {
      await apiClient().submitReworkExplanation({
        context_text: context.trim(),
        difficulty_text: difficulty.trim(),
        support_request_text: ask.trim(),
        case_id: caseId,
      });
      setSent(true);
      toast.success("Đã gửi — bên mua sắm sẽ xem và liên hệ hỗ trợ.");
      onSubmitted?.();
      refresh();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Chưa gửi được, thử lại nhé.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className={blocked ? "border-warning/60" : "border-muted"}>
      <CardHeader>
        <CardTitle className="flex items-start gap-2 text-base">
          <HeartHandshake className="mt-0.5 size-4 shrink-0 text-primary" />
          <span>{support.headline}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {support.lines.map((line, index) => (
          <p key={index} className="text-sm text-muted-foreground">
            {line}
          </p>
        ))}

        {sent ? (
          <p className="rounded-lg bg-[#eef5fb] px-3 py-2 text-sm text-primary">
            Đã ghi nhận phần mô tả của bạn. Bên mua sắm sẽ xem và trao đổi lại.
          </p>
        ) : (
          !DW01_READONLY && (
            <div className="space-y-3 rounded-lg border p-3">
              <p className="text-sm font-medium">{support.prompt}</p>
              <Textarea
                rows={3}
                placeholder="Bối cảnh: đợt vừa rồi có gì đang vướng?"
                value={context}
                onChange={(event) => setContext(event.target.value)}
              />
              <Textarea
                rows={2}
                placeholder="Khó khăn cụ thể (không bắt buộc)"
                value={difficulty}
                onChange={(event) => setDifficulty(event.target.value)}
              />
              <Textarea
                rows={2}
                placeholder="Mong được hỗ trợ gì (không bắt buộc)"
                value={ask}
                onChange={(event) => setAsk(event.target.value)}
              />
              <div className="flex items-center gap-3">
                <Button
                  onClick={() => void submit()}
                  disabled={busy || tooShort}
                >
                  {busy ? "Đang gửi…" : "Gửi cho bên mua sắm"}
                </Button>
                {tooShort && (
                  <span className="text-xs text-muted-foreground">
                    Cần thêm{" "}
                    {support.explanation_min_chars - context.trim().length} ký
                    tự nữa.
                  </span>
                )}
              </div>
            </div>
          )
        )}
      </CardContent>
    </Card>
  );
}
