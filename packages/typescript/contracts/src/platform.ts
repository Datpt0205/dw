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
});
export type KnowledgeDocument = z.infer<typeof knowledgeDocumentSchema>;

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
