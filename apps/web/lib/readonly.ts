/**
 * Conversation-first mode: the web UI is a READ-ONLY back office (timeline,
 * artifacts, documents, audit). All actions — create, verify, decide CP1–CP4,
 * publish, addendum, submissions — happen in Slack.
 *
 * Default ON. Build with NEXT_PUBLIC_DW01_READONLY=false to re-enable the
 * legacy web actions (e.g. for regression testing without Slack).
 */
export const DW01_READONLY = process.env.NEXT_PUBLIC_DW01_READONLY !== "false";

export const READONLY_NOTICE =
  "Thao tác này được thực hiện qua Slack — web chỉ dùng để theo dõi và tra cứu.";
