"use client";

import type { ReactNode } from "react";
import { BadgeCheck, CalendarDays, ClipboardList } from "lucide-react";
import { AreaShell } from "../../components/area-shell";

export default function MeetingsLayout({ children }: { children: ReactNode }) {
  return (
    <AreaShell
      title="Quản lý cuộc họp"
      icon={ClipboardList}
      items={[
        {
          href: "/meetings",
          label: "Cuộc họp",
          icon: CalendarDays,
          exact: true,
        },
        { href: "/meetings/approvals", label: "Phê duyệt", icon: BadgeCheck },
      ]}
    >
      {children}
    </AreaShell>
  );
}
