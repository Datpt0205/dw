"use client";

import type { ReactNode } from "react";
import { BadgeCheck, FileSearch, FolderOpen } from "lucide-react";
import { AreaShell } from "../../components/area-shell";

export default function TenderLayout({ children }: { children: ReactNode }) {
  return (
    <AreaShell
      title="Phân tích đấu thầu"
      icon={FileSearch}
      items={[
        { href: "/tender", label: "Hồ sơ thầu", icon: FolderOpen, exact: true },
        { href: "/tender/approvals", label: "Phê duyệt", icon: BadgeCheck },
      ]}
    >
      {children}
    </AreaShell>
  );
}
