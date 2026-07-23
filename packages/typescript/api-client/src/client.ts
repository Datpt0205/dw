import { z } from "zod";
import {
  actionItemSchema,
  approvalSchema,
  errorResponseSchema,
  healthResponseSchema,
  meetingSchema,
  readinessResponseSchema,
  runSchema,
  timelineEventSchema,
  type Approval,
  type ErrorResponse,
  type HealthResponse,
  type Meeting,
  type ReadinessResponse,
  type Run,
  type TimelineEvent,
} from "@dw/contracts";

/**
 * Typed API client core. Endpoint methods generated from OpenAPI are layered on
 * top of this transport in phase 3; hand-written duplicate types are forbidden.
 */

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: ErrorResponse,
  ) {
    super(`${body.code}: ${body.message}`);
    this.name = "ApiError";
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  /** Returns the bearer token for the current session, if any. */
  getAccessToken?: () => Promise<string | null> | string | null;
  fetchImpl?: typeof fetch;
}

export class ApiClient {
  constructor(private readonly options: ApiClientOptions) {}

  async request<T>(
    method: "GET" | "POST" | "PATCH" | "DELETE",
    path: string,
    schema: z.ZodType<T>,
    init?: { body?: unknown; idempotencyKey?: string },
  ): Promise<T> {
    const fetchImpl = this.options.fetchImpl ?? fetch;
    const headers: Record<string, string> = { Accept: "application/json" };

    const token = await this.options.getAccessToken?.();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (init?.body !== undefined) headers["Content-Type"] = "application/json";
    if (init?.idempotencyKey) headers["Idempotency-Key"] = init.idempotencyKey;

    const response = await fetchImpl(`${this.options.baseUrl}${path}`, {
      method,
      headers,
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
    });

    const json: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const parsedError = errorResponseSchema.safeParse(json);
      throw new ApiError(
        response.status,
        parsedError.success
          ? parsedError.data
          : {
              code: "internal",
              message: `HTTP ${response.status}`,
              details: {},
            },
      );
    }
    return schema.parse(json);
  }

  getHealth(): Promise<HealthResponse> {
    return this.request("GET", "/api/v1/health", healthResponseSchema);
  }

  getReadiness(): Promise<ReadinessResponse> {
    return this.request("GET", "/api/v1/ready", readinessResponseSchema);
  }

  // ---- work-ops -----------------------------------------------------------

  listMeetings(): Promise<Meeting[]> {
    return this.request(
      "GET",
      "/api/v1/work-ops/meetings",
      z.array(meetingSchema),
    );
  }

  getMeeting(meetingId: string): Promise<Meeting> {
    return this.request(
      "GET",
      `/api/v1/work-ops/meetings/${meetingId}`,
      meetingSchema,
    );
  }

  createMeeting(input: {
    title: string;
    occurred_at: string;
    transcript_text: string;
    transcript_filename?: string;
  }): Promise<{ meeting_id: string }> {
    return this.request(
      "POST",
      "/api/v1/work-ops/meetings",
      z.object({ meeting_id: z.string().uuid() }),
      { body: input },
    );
  }

  generateActions(meetingId: string): Promise<{ run_id: string }> {
    return this.request(
      "POST",
      `/api/v1/work-ops/meetings/${meetingId}/generate-actions`,
      z.object({ run_id: z.string().uuid() }),
      { body: {} },
    );
  }

  // ---- approvals / runs ---------------------------------------------------

  listApprovals(): Promise<Approval[]> {
    return this.request("GET", "/api/v1/approvals", z.array(approvalSchema));
  }

  decideApproval(
    approvalId: string,
    decision: { approve: boolean; comment?: string },
  ): Promise<Approval> {
    return this.request(
      "POST",
      `/api/v1/approvals/${approvalId}/decisions`,
      approvalSchema,
      { body: decision },
    );
  }

  getRun(runId: string): Promise<Run> {
    return this.request("GET", `/api/v1/runs/${runId}`, runSchema);
  }

  getRunTimeline(runId: string): Promise<TimelineEvent[]> {
    return this.request(
      "GET",
      `/api/v1/runs/${runId}/timeline`,
      z.array(timelineEventSchema),
    );
  }
}

export type { Approval, Meeting, Run, TimelineEvent };
export { actionItemSchema };
