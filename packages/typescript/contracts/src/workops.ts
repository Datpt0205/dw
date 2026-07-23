import { z } from "zod";

/** Mirrors dw_work_ops.application.dto + platform approval/run views. */

export const actionItemSchema = z.object({
  id: z.string().uuid(),
  title: z.string(),
  description: z.string(),
  status: z.enum(["proposed", "approved", "dispatched", "rejected"]),
  assignee_display_name: z.string().nullable(),
  assignee_department: z.string().nullable(),
  assignee_confidence: z.number(),
  due_date: z.string().nullable(),
  due_date_inferred: z.boolean(),
  risk_level: z.string(),
  approval_reasons: z.array(z.string()),
  external_ref: z.string().nullable().optional(),
  external_url: z.string().nullable().optional(),
});
export type ActionItem = z.infer<typeof actionItemSchema>;

export const decisionSchema = z.object({
  id: z.string().uuid(),
  statement: z.string(),
  decided_by_name: z.string().nullable(),
  evidence_quote: z.string().nullable(),
});
export type Decision = z.infer<typeof decisionSchema>;

export const analysisPointSchema = z.object({
  point: z.string(),
  evidence_quote: z.string().nullable(),
});
export type AnalysisPoint = z.infer<typeof analysisPointSchema>;

export const meetingAnalysisSchema = z.object({
  overall_assessment: z.string(),
  effectiveness_score: z.number().int().min(1).max(10),
  went_well: z.array(analysisPointSchema),
  needs_improvement: z.array(analysisPointSchema),
  recommendations: z.array(z.string()),
});
export type MeetingAnalysis = z.infer<typeof meetingAnalysisSchema>;

export const meetingSchema = z.object({
  id: z.string().uuid(),
  title: z.string(),
  occurred_at: z.string(),
  status: z.enum(["created", "processing", "actions_ready", "completed"]),
  summary: z.record(z.string(), z.unknown()).nullable(),
  analysis: meetingAnalysisSchema.nullable(),
  last_run_id: z.string().uuid().nullable(),
  decisions: z.array(decisionSchema),
  actions: z.array(actionItemSchema),
});
export type Meeting = z.infer<typeof meetingSchema>;

export const approvalSchema = z.object({
  id: z.string().uuid(),
  approval_type: z.string(),
  reason: z.string(),
  status: z.enum(["pending", "approved", "rejected", "cancelled"]),
  run_id: z.string().uuid().nullable(),
  payload: z.record(z.string(), z.unknown()),
  created_at: z.string().nullable(),
  decided_at: z.string().nullable(),
});
export type Approval = z.infer<typeof approvalSchema>;

export const runSchema = z.object({
  id: z.string().uuid(),
  status: z.enum([
    "pending",
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
  ]),
  worker_id: z.string(),
  worker_version: z.string(),
  graph_version: z.string(),
  result: z.record(z.string(), z.unknown()).nullable(),
  error: z.record(z.string(), z.unknown()).nullable(),
  approval_request_id: z.string().uuid().nullable(),
  release_manifest_ref: z.string().nullable(),
});
export type Run = z.infer<typeof runSchema>;

export const timelineEventSchema = z.object({
  action: z.string(),
  resource_type: z.string(),
  resource_id: z.string(),
  policy_decision: z.string().nullable(),
  occurred_at: z.string(),
  details: z.record(z.string(), z.unknown()),
});
export type TimelineEvent = z.infer<typeof timelineEventSchema>;
