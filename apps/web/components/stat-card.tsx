import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@dw/ui";

interface StatCardProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon: LucideIcon;
  tone?: "neutral" | "primary" | "warning" | "success";
}

const TONES = {
  neutral: "bg-slate-100 text-slate-600",
  primary: "bg-[#e6eff7] text-primary",
  warning: "bg-amber-50 text-amber-700",
  success: "bg-emerald-50 text-emerald-700",
};

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "neutral",
}: StatCardProps) {
  return (
    <div className="rounded-2xl border border-border/80 bg-card p-4 shadow-[0_6px_20px_rgba(11,49,85,0.05)] sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            {label}
          </p>
          <div className="mt-2 text-2xl font-semibold tracking-tight">
            {value}
          </div>
        </div>
        <span
          className={cn(
            "flex size-9 shrink-0 items-center justify-center rounded-xl",
            TONES[tone],
          )}
        >
          <Icon className="size-[18px]" />
        </span>
      </div>
      {hint && <div className="mt-2 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}
