import { z } from "zod";

/** Response of GET /api/v1/health */
export const healthResponseSchema = z.object({
  status: z.literal("ok"),
  version: z.string(),
  api_version: z.string(),
});
export type HealthResponse = z.infer<typeof healthResponseSchema>;

/** Response of GET /api/v1/ready */
export const readinessResponseSchema = z.object({
  status: z.enum(["ready", "not_ready"]),
  checks: z.record(z.string(), z.enum(["ok", "failed", "not_configured"])),
});
export type ReadinessResponse = z.infer<typeof readinessResponseSchema>;
