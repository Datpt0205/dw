"use client";

import { ApprovalsView } from "../../../components/approvals-view";

export default function TenderApprovalsPage() {
  return (
    <ApprovalsView
      typePrefix="tender."
      emptyHint="Không có đề xuất thầu nào đang chờ — chạy Phân tích ở một hồ sơ trước."
    />
  );
}
