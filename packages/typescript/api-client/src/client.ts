import { z } from "zod";
import {
  actionItemSchema,
  approvalSchema,
  auditEventSchema,
  demoUserSchema,
  devSessionSchema,
  integrationSchema,
  knowledgeDocumentSchema,
  ingestJobSchema,
  memoryItemSchema,
  errorResponseSchema,
  healthResponseSchema,
  meetingSchema,
  readinessResponseSchema,
  runSchema,
  timelineEventSchema,
  tenderCaseSchema,
  type Approval,
  type AuditEvent,
  type DemoUser,
  type DevSessionInfo,
  type ErrorResponse,
  type Integration,
  type KnowledgeDocument,
  type IngestJob,
  type MemoryItem,
  type HealthResponse,
  type Meeting,
  type ReadinessResponse,
  type Run,
  type TenderCase,
  type TimelineEvent,
} from "@dw/contracts";

/**
 * Typed API client core. Endpoint methods generated from OpenAPI are layered on
 * top of this transport in phase 3; hand-written duplicate types are forbidden.
 */

// ---- DW01 preparation (inline schemas; validated at the boundary) ---------
export const preparationArtifactSchema = z.object({
  id: z.string(),
  artifact_type: z.string(),
  artifact_version: z.number(),
  status: z.string(),
  content: z.record(z.unknown()),
  content_hash: z.string(),
});
export const preparationCaseSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string(),
  source_pr_ref: z.string(),
  estimated_value_minor: z.number(),
  currency: z.string(),
  deadline: z.string().nullable(),
  owner_name: z.string(),
  method_key: z.string().nullable(),
  state: z.string(),
  current_step: z.string(),
  last_run_id: z.string().nullable(),
  export_ref: z.string().nullable(),
  current_official_artifact_id: z.string().nullable(),
  version: z.number(),
  artifacts: z.array(preparationArtifactSchema),
});
export type PreparationArtifact = z.infer<typeof preparationArtifactSchema>;
export type PreparationCase = z.infer<typeof preparationCaseSchema>;

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

  // ---- dev demo (local only; the API refuses these in production) ---------

  listDemoUsers(): Promise<DemoUser[]> {
    return this.request(
      "GET",
      "/api/v1/dev/demo-users",
      z.array(demoUserSchema),
    );
  }

  createDevSession(subject: string): Promise<DevSessionInfo> {
    return this.request("POST", "/api/v1/dev/session", devSessionSchema, {
      body: { subject },
    });
  }

  createDemoTenderCase(): Promise<{ case_id: string }> {
    return this.request(
      "POST",
      "/api/v1/dev/demo/tender-case",
      z.object({ case_id: z.string().uuid() }),
      { body: {} },
    );
  }

  createDemoMeeting(): Promise<{ meeting_id: string }> {
    return this.request(
      "POST",
      "/api/v1/dev/demo/meeting",
      z.object({ meeting_id: z.string().uuid() }),
      { body: {} },
    );
  }

  // ---- platform inventories ----------------------------------------------

  listKnowledgeDocuments(limit = 100): Promise<KnowledgeDocument[]> {
    return this.request(
      "GET",
      `/api/v1/knowledge/documents?limit=${limit}`,
      z.array(knowledgeDocumentSchema),
    );
  }

  /** Upload a raw file for async ingestion (multipart). Returns the queued job. */
  async uploadKnowledgeDocument(
    file: File | Blob,
    meta: {
      title: string;
      filename?: string;
      domain?: string;
      classification?: string;
      source_version?: string;
      scope?: "tenant" | "global";
    },
  ): Promise<IngestJob> {
    const fetchImpl = this.options.fetchImpl ?? fetch;
    const form = new FormData();
    const filename =
      meta.filename ?? (file instanceof File ? file.name : "document");
    form.append("file", file, filename);
    form.append("title", meta.title);
    if (meta.domain) form.append("domain", meta.domain);
    if (meta.classification) form.append("classification", meta.classification);
    if (meta.source_version) form.append("source_version", meta.source_version);
    if (meta.scope) form.append("scope", meta.scope);

    // No Content-Type header: the browser sets multipart boundary itself.
    const headers: Record<string, string> = { Accept: "application/json" };
    const token = await this.options.getAccessToken?.();
    if (token) headers.Authorization = `Bearer ${token}`;

    const response = await fetchImpl(
      `${this.options.baseUrl}/api/v1/knowledge/documents`,
      { method: "POST", headers, body: form },
    );
    const json: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const parsed = errorResponseSchema.safeParse(json);
      throw new ApiError(
        response.status,
        parsed.success
          ? parsed.data
          : { code: "internal", message: `HTTP ${response.status}`, details: {} },
      );
    }
    return ingestJobSchema.parse(json);
  }

  getIngestJob(jobId: string): Promise<IngestJob> {
    return this.request(
      "GET",
      `/api/v1/knowledge/documents/jobs/${jobId}`,
      ingestJobSchema,
    );
  }

  async deleteKnowledgeDocument(documentId: string): Promise<void> {
    const fetchImpl = this.options.fetchImpl ?? fetch;
    const headers: Record<string, string> = { Accept: "application/json" };
    const token = await this.options.getAccessToken?.();
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetchImpl(
      `${this.options.baseUrl}/api/v1/knowledge/documents/${documentId}`,
      { method: "DELETE", headers },
    );
    if (!response.ok && response.status !== 204) {
      const json: unknown = await response.json().catch(() => null);
      const parsed = errorResponseSchema.safeParse(json);
      throw new ApiError(
        response.status,
        parsed.success
          ? parsed.data
          : { code: "internal", message: `HTTP ${response.status}`, details: {} },
      );
    }
  }

  listMemoryItems(limit = 100): Promise<MemoryItem[]> {
    return this.request(
      "GET",
      `/api/v1/memory/items?limit=${limit}`,
      z.array(memoryItemSchema),
    );
  }

  listIntegrations(): Promise<Integration[]> {
    return this.request(
      "GET",
      "/api/v1/integrations",
      z.array(integrationSchema),
    );
  }

  // ---- audit --------------------------------------------------------------

  listAuditEvents(limit = 100): Promise<AuditEvent[]> {
    return this.request(
      "GET",
      `/api/v1/audit/events?limit=${limit}`,
      z.array(auditEventSchema),
    );
  }

  // ---- procurement --------------------------------------------------------

  listTenderCases(): Promise<TenderCase[]> {
    return this.request(
      "GET",
      "/api/v1/procurement/cases",
      z.array(tenderCaseSchema),
    );
  }

  getTenderCase(caseId: string): Promise<TenderCase> {
    return this.request(
      "GET",
      `/api/v1/procurement/cases/${caseId}`,
      tenderCaseSchema,
    );
  }

  createTenderCase(input: {
    title: string;
    description?: string;
    documents: Array<{
      kind: "rfq" | "supplier_submission" | "other";
      title: string;
      content: string;
      supplier_name?: string | null;
    }>;
  }): Promise<{ case_id: string }> {
    return this.request(
      "POST",
      "/api/v1/procurement/cases",
      z.object({ case_id: z.string().uuid() }),
      { body: input },
    );
  }

  analyzeTenderCase(caseId: string): Promise<{ run_id: string }> {
    return this.request(
      "POST",
      `/api/v1/procurement/cases/${caseId}/analyze`,
      z.object({ run_id: z.string().uuid() }),
      { body: {} },
    );
  }

  // ---- DW01 preparation ---------------------------------------------------

  listPreparationCases(): Promise<PreparationCase[]> {
    return this.request(
      "GET",
      "/api/v1/procurement/preparation/cases",
      z.array(preparationCaseSchema),
    );
  }

  getPreparationCase(caseId: string): Promise<PreparationCase> {
    return this.request(
      "GET",
      `/api/v1/procurement/preparation/cases/${caseId}`,
      preparationCaseSchema,
    );
  }

  createPreparationCase(input: {
    title: string;
    description?: string;
    source_pr_ref?: string;
    estimated_value_minor?: number;
    currency?: string;
    deadline?: string | null;
    owner_name?: string;
    pr_text: string;
  }): Promise<{ case_id: string }> {
    return this.request(
      "POST",
      "/api/v1/procurement/preparation/cases",
      z.object({ case_id: z.string().uuid() }),
      { body: input },
    );
  }

  runPreparation(caseId: string): Promise<{ run_id: string }> {
    return this.request(
      "POST",
      `/api/v1/procurement/preparation/cases/${caseId}/run`,
      z.object({ run_id: z.string().uuid() }),
      { body: {} },
    );
  }
}

export type { Approval, AuditEvent, Meeting, Run, TenderCase, TimelineEvent };
export { actionItemSchema };
