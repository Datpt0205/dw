import { z } from "zod";

export const knowledgeDocumentSchema = z.object({
  document_id: z.string().uuid(),
  title: z.string(),
  domain: z.string(),
  classification: z.string(),
  source_version: z.string(),
  index_version: z.string().nullable(),
  chunk_count: z.number().int(),
  created_at: z.string(),
  scope: z.string(),
});
export type KnowledgeDocument = z.infer<typeof knowledgeDocumentSchema>;

export const ingestJobSchema = z.object({
  job_id: z.string().uuid(),
  status: z.string(),
  title: z.string(),
  filename: z.string(),
  scope: z.string(),
  attempts: z.number().int(),
  error: z.string().nullable(),
  document_id: z.string().uuid().nullable(),
  chunk_count: z.number().int().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type IngestJob = z.infer<typeof ingestJobSchema>;

export const memoryItemSchema = z.object({
  memory_id: z.string().uuid(),
  worker_id: z.string(),
  memory_type: z.string(),
  content: z.string(),
  confidence: z.number(),
  classification: z.string(),
  provenance_count: z.number().int(),
  valid_from: z.string(),
  created_by_run_id: z.string().uuid(),
});
export type MemoryItem = z.infer<typeof memoryItemSchema>;

export const integrationSchema = z.object({
  tool: z.string(),
  version: z.string(),
  description: z.string(),
  side_effect_level: z.string(),
  approval_policy: z.string(),
  requires_approval: z.boolean(),
  idempotent: z.boolean(),
  timeout_seconds: z.number().int(),
  required_scopes: z.array(z.string()),
});
export type Integration = z.infer<typeof integrationSchema>;

// Chat accounts a person has connected. `account` is the chat-side id — shown
// so somebody can tell which of their accounts is linked, nothing more.
export const channelLinkStatusSchema = z.object({
  channel: z.string(),
  linked: z.boolean(),
  account: z.string().nullable().optional(),
});
export type ChannelLinkStatus = z.infer<typeof channelLinkStatusSchema>;

export const channelLinkCodeSchema = z.object({
  code: z.string(),
  expires_at: z.string(),
  channel: z.string(),
});
export type ChannelLinkCode = z.infer<typeof channelLinkCodeSchema>;
