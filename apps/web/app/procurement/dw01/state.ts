type Variant = "secondary" | "warning" | "success" | "destructive";

const MAP: Record<string, { label: string; variant: Variant }> = {
  draft: { label: "Nháp", variant: "secondary" },
  intake_ready: { label: "Sẵn sàng chạy", variant: "secondary" },
  analyzing: { label: "Đang xử lý", variant: "warning" },
  waiting_clarification: { label: "Cần làm rõ", variant: "warning" },
  approach_ready: { label: "Có phương án", variant: "warning" },
  cp1_pending: { label: "Chờ duyệt CP1", variant: "warning" },
  cp1_rejected: { label: "CP1 từ chối", variant: "destructive" },
  cp1_approved: { label: "CP1 đã duyệt", variant: "warning" },
  building_solicitation: { label: "Đang xây hồ sơ", variant: "warning" },
  package_ready: { label: "Hồ sơ sẵn sàng", variant: "warning" },
  cp2_pending: { label: "Chờ duyệt CP2", variant: "warning" },
  cp2_rejected: { label: "CP2 từ chối", variant: "destructive" },
  cp2_approved: { label: "CP2 đã duyệt", variant: "success" },
  package_official: { label: "Chính thức", variant: "success" },
  completed: { label: "Hoàn tất", variant: "success" },
  failed: { label: "Thất bại", variant: "destructive" },
};

export function STATE_BADGE(state: string): { label: string; variant: Variant } {
  return MAP[state] ?? { label: state, variant: "secondary" };
}

export function formatVnd(minor: number): string {
  return `${minor.toLocaleString("vi-VN")} VND`;
}

/** Ordered checkpoint steps for the case stepper. */
export const STEPPER: { key: string; label: string; states: string[] }[] = [
  { key: "intake", label: "Chuẩn hoá nhu cầu", states: ["intake_ready", "analyzing", "waiting_clarification", "approach_ready"] },
  { key: "cp1", label: "CP1 — Phương án", states: ["cp1_pending", "cp1_approved"] },
  { key: "build", label: "Xây hồ sơ", states: ["building_solicitation", "package_ready"] },
  { key: "cp2", label: "CP2 — Bộ hồ sơ", states: ["cp2_pending", "cp2_approved"] },
  { key: "official", label: "Chính thức", states: ["package_official", "completed"] },
];

export function currentStepIndex(state: string): number {
  const idx = STEPPER.findIndex((s) => s.states.includes(state));
  if (idx >= 0) return idx;
  if (state === "cp1_rejected") return 1;
  if (state === "cp2_rejected") return 3;
  return 0;
}
