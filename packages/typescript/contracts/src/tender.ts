import { z } from "zod";

/** Mirrors dw_tender.application.dto views. */

export const requirementSchema = z.object({
  id: z.string().uuid(),
  code: z.string(),
  statement: z.string(),
  kind: z.enum(["mandatory", "weighted", "informational"]),
  weight: z.string(),
});
export type Requirement = z.infer<typeof requirementSchema>;

export const findingSchema = z.object({
  requirement_code: z.string(),
  supplier_name: z.string(),
  status: z.enum(["compliant", "non_compliant", "missing_evidence"]),
  raw_score: z.string(),
  note: z.string(),
  evidence_count: z.number(),
  quote: z.string().nullable(),
});
export type Finding = z.infer<typeof findingSchema>;

export const supplierScoreSchema = z.object({
  supplier_name: z.string(),
  total_score: z.string(),
  mandatory_passed: z.boolean(),
  eligible: z.boolean(),
  violations: z.array(z.string()),
});
export type SupplierScore = z.infer<typeof supplierScoreSchema>;

export const recommendationSchema = z.object({
  recommended_supplier: z.string().nullable(),
  rationale: z.string(),
  supplier_scores: z.array(supplierScoreSchema),
  risks: z.array(z.string()),
  gate_passed: z.boolean(),
  gate_violations: z.array(z.string()),
  scoring_policy_version: z.string(),
  confidence: z.number(),
  evidence_count: z.number(),
});
export type Recommendation = z.infer<typeof recommendationSchema>;

export const tenderCaseSchema = z.object({
  id: z.string().uuid(),
  title: z.string(),
  description: z.string(),
  status: z.enum(["created", "analyzing", "recommendation_ready", "completed"]),
  last_run_id: z.string().uuid().nullable(),
  export_ref: z.string().nullable(),
  requirements: z.array(requirementSchema),
  findings: z.array(findingSchema),
  recommendation: recommendationSchema.nullable(),
});
export type TenderCase = z.infer<typeof tenderCaseSchema>;
