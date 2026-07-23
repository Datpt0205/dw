import { z } from "zod";

/**
 * Unified API error envelope (blueprint §16.1).
 * Mirrors `dw_api.errors.ErrorResponse` — every endpoint returns this shape on failure.
 */
export const errorResponseSchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.record(z.string(), z.unknown()).default({}),
  request_id: z.string().nullable().optional(),
});

export type ErrorResponse = z.infer<typeof errorResponseSchema>;

/** Stable error codes shared with the backend taxonomy. */
export const ErrorCode = {
  ValidationFailed: "validation_failed",
  NotFound: "not_found",
  Conflict: "conflict",
  PermissionDenied: "permission_denied",
  EntitlementDenied: "entitlement_denied",
  ApprovalRequired: "approval_required",
  TenantContextMissing: "tenant_context_missing",
  IdempotencyConflict: "idempotency_conflict",
  RateLimited: "rate_limited",
  Timeout: "timeout",
  UpstreamUnavailable: "upstream_unavailable",
  Internal: "internal",
} as const;

export type ErrorCodeValue = (typeof ErrorCode)[keyof typeof ErrorCode];
