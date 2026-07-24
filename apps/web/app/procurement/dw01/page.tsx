"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { FilePlus2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import type { PreparationCase } from "@dw/api-client";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Textarea,
} from "@dw/ui";
import { useAuth } from "../../../lib/auth/auth-context";
import { apiClient } from "../../../lib/session";
import { STATE_BADGE, formatVnd } from "./state";

const DEMO_PR = `PHIẾU YÊU CẦU MUA SẮM (PR) — ĐÃ PHÊ DUYỆT
Mã PR: PR-2026-0042 (ĐÃ DUYỆT)
Người yêu cầu: Phòng CNTT — Khối Vận hành
Chủ sở hữu (owner): Nguyễn Văn An

1. NHU CẦU
Mua 100 máy tính xách tay cho khối vận hành mở rộng quý 3/2026.

2. NGÂN SÁCH: 2.500.000.000 VND
3. THỜI HẠN: giao trong 45 ngày kể từ ngày ký hợp đồng.

4. YÊU CẦU KỸ THUẬT (SƠ BỘ)
- CPU tối thiểu Core i5 thế hệ mới
- RAM tối thiểu 16 GB
- SSD tối thiểu 512 GB
- Màn hình 14 inch Full HD
- Bảo hành (CHƯA RÕ số năm bảo hành tối thiểu)
- Hệ điều hành (CHƯA RÕ Windows bản quyền hay không)

5. YÊU CẦU THƯƠNG MẠI
- Địa điểm giao (CHƯA RÕ)
- Điều khoản thanh toán (CHƯA RÕ)`;

export default function Dw01ListPage() {
  const router = useRouter();
  const { hasScope } = useAuth();
  const canCreate = hasScope("tender.write");
  const [cases, setCases] = useState<PreparationCase[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("Mua 100 laptop khối vận hành");
  const [value, setValue] = useState("2500000000");
  const [prText, setPrText] = useState(DEMO_PR);

  const refresh = useCallback(() => {
    apiClient()
      .listPreparationCases()
      .then(setCases)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "lỗi không rõ"),
      );
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function create(demo: boolean) {
    setBusy(true);
    setError(null);
    try {
      const { case_id } = await apiClient().createPreparationCase({
        title: demo ? "Mua 100 laptop khối vận hành (mẫu)" : title,
        source_pr_ref: "PR-2026-0042",
        estimated_value_minor: demo ? 2_500_000_000 : Number(value) || 0,
        currency: "VND",
        deadline: "45 ngày",
        owner_name: "Nguyễn Văn An",
        pr_text: demo ? DEMO_PR : prText,
      });
      toast.success("Đã tạo hồ sơ — mở để chạy DW01.");
      router.push(`/procurement/dw01/cases/${case_id}`);
    } catch (e) {
      const m = e instanceof Error ? e.message : "lỗi không rõ";
      setError(m);
      toast.error(m);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Xây hồ sơ mời thầu (DW01)
          </h1>
          <p className="text-sm text-muted-foreground">
            PR đã duyệt → phương án (CP1) → bộ hồ sơ RFQ/tiêu chí/shortlist (CP2)
            → bản chính thức.
          </p>
        </div>
        {canCreate && (
          <Button onClick={() => void create(true)} disabled={busy}>
            <Sparkles /> Tạo hồ sơ mẫu
          </Button>
        )}
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {canCreate && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Tạo hồ sơ từ PR</CardTitle>
            <CardDescription>
              Dán nội dung PR đã phê duyệt; các điểm «CHƯA RÕ» sẽ thành danh sách
              làm rõ.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input
              placeholder="Tiêu đề hồ sơ"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <Input
              placeholder="Giá trị gói (VND)"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            <Textarea
              rows={6}
              value={prText}
              onChange={(e) => setPrText(e.target.value)}
            />
            <Button
              variant="outline"
              onClick={() => void create(false)}
              disabled={busy}
            >
              <FilePlus2 /> Tự nhập
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="space-y-2">
        {cases?.length === 0 && (
          <Card>
            <CardContent className="pt-5 text-sm text-muted-foreground">
              Chưa có hồ sơ nào — bấm <strong>Tạo hồ sơ mẫu</strong> để bắt đầu.
            </CardContent>
          </Card>
        )}
        {cases?.map((c) => {
          const badge = STATE_BADGE(c.state);
          return (
            <Link key={c.id} href={`/procurement/dw01/cases/${c.id}`}>
              <Card className="transition-colors hover:border-primary/50">
                <CardContent className="flex items-center justify-between gap-3 pt-4">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{c.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {formatVnd(c.estimated_value_minor)}
                      {c.method_key ? ` · ${c.method_key}` : ""}
                    </p>
                  </div>
                  <Badge variant={badge.variant}>{badge.label}</Badge>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
