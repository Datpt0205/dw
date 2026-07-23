"use client";

import { ApprovalsView } from "../../../components/approvals-view";

export default function MeetingApprovalsPage() {
  return (
    <ApprovalsView
      typePrefix="work_ops."
      emptyHint="Không có action item nào chờ duyệt — chạy Sinh action items ở một cuộc họp trước."
    />
  );
}
