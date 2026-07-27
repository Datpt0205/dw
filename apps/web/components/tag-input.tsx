"use client";

import { useState } from "react";
import { Plus, X } from "lucide-react";
import { Button, Input } from "@dw/ui";

interface TagInputProps {
  id: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder: string;
  addLabel?: string;
  helpText?: string;
}

export function TagInput({
  id,
  values,
  onChange,
  placeholder,
  addLabel = "Thêm",
  helpText,
}: TagInputProps) {
  const [draft, setDraft] = useState("");

  function add(rawValue = draft) {
    const known = new Set(values.map((item) => item.toLocaleLowerCase("vi")));
    const additions = rawValue
      .split(/[\n,;]+/)
      .map((item) => item.trim())
      .filter((item) => {
        if (!item) return false;
        const key = item.toLocaleLowerCase("vi");
        if (known.has(key)) return false;
        known.add(key);
        return true;
      });
    if (additions.length === 0) return;
    onChange([...values, ...additions]);
    setDraft("");
  }

  return (
    <>
      <div className="rounded-xl border bg-white p-3 shadow-sm focus-within:border-primary/50 focus-within:ring-2 focus-within:ring-primary/10">
        {values.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {values.map((value) => (
              <span
                key={value}
                className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-[#e7f0f7] px-3 py-1.5 text-sm font-medium text-primary"
              >
                <span className="truncate">{value}</span>
                <button
                  type="button"
                  onClick={() =>
                    onChange(values.filter((item) => item !== value))
                  }
                  className="rounded-full p-0.5 hover:bg-primary/10"
                  aria-label={`Xóa ${value}`}
                >
                  <X className="size-3.5" />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            id={id}
            className="border-0 px-1 shadow-none focus-visible:ring-0"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" ||
                event.key === "," ||
                event.key === ";"
              ) {
                event.preventDefault();
                add();
              }
            }}
            onPaste={(event) => {
              const pasted = event.clipboardData.getData("text");
              if (/[\n,;]/.test(pasted)) {
                event.preventDefault();
                add(pasted);
              }
            }}
            placeholder={placeholder}
          />
          <Button
            type="button"
            variant="outline"
            className="shrink-0"
            disabled={!draft.trim()}
            onClick={() => add()}
          >
            <Plus /> {addLabel}
          </Button>
        </div>
      </div>
      {helpText && (
        <p className="mt-1.5 text-xs text-muted-foreground">{helpText}</p>
      )}
    </>
  );
}
