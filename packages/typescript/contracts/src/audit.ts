import { z } from "zod";

export const auditEventSchema = z.object({
  action: z.string(),
  resource_type: z.string(),
  resource_id: z.string(),
  policy_decision: z.string().nullable(),
  trace_id: z.string().nullable(),
  occurred_at: z.string(),
  details: z.record(z.string(), z.unknown()),
});
export type AuditEvent = z.infer<typeof auditEventSchema>;
