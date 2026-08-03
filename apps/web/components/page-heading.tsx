import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@dw/ui";

interface PageHeadingProps {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  icon?: LucideIcon;
  actions?: ReactNode;
  className?: string;
}

export function PageHeading({
  eyebrow,
  title,
  description,
  icon: Icon,
  actions,
  className,
}: PageHeadingProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-4 border-b border-border/70 pb-5 sm:flex-row sm:items-end sm:justify-between",
        className,
      )}
    >
      <div className="min-w-0">
        {eyebrow && (
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-primary/70">
            {Icon && <Icon className="size-4" />}
            {eyebrow}
          </div>
        )}
        <h1 className="text-2xl font-semibold tracking-[-0.025em] text-foreground sm:text-[1.75rem]">
          {title}
        </h1>
        {description && (
          <div className="mt-1.5 max-w-3xl text-sm leading-6 text-muted-foreground">
            {description}
          </div>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {actions}
        </div>
      )}
    </div>
  );
}
