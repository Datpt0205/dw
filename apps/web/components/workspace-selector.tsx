"use client";

import { Building2, Check, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "@dw/ui";
import { useAuth } from "../lib/auth/auth-context";

/** Compact workspace switcher in the header (only when 2+ memberships). */
export function WorkspaceSelector() {
  const { memberships, active, selectWorkspace } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  if (!active) return null;

  const single = memberships.length <= 1;
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        disabled={single}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-2 rounded-full border bg-card px-3 py-1.5 text-sm shadow-sm",
          !single && "hover:bg-accent",
        )}
      >
        <Building2 className="size-4 text-muted-foreground" />
        <span className="max-w-40 truncate font-medium">
          {active.workspaceName}
        </span>
        <span className="text-xs text-muted-foreground">
          {active.tenantName}
        </span>
        {!single && <ChevronDown className="size-3.5 text-muted-foreground" />}
      </button>

      {open && (
        <div className="absolute right-0 z-20 mt-1 w-64 rounded-lg border bg-popover p-1 shadow-md">
          {memberships.map((m) => (
            <button
              key={m.workspaceId}
              type="button"
              onClick={() => {
                selectWorkspace(m.workspaceId);
                setOpen(false);
              }}
              className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-2 text-left text-sm hover:bg-accent"
            >
              <span className="min-w-0">
                <span className="block truncate font-medium">
                  {m.workspaceName}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {m.tenantName}
                </span>
              </span>
              {m.workspaceId === active.workspaceId && (
                <Check className="size-4 text-primary" />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
