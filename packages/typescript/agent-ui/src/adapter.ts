import { z } from "zod";

/**
 * UI/agent adapter boundary (ADR-007).
 *
 * The web app talks to agent runs ONLY through this interface. CopilotKit is
 * one implementation (phase 3); the REST-polling mock below is another. Domain
 * pages must never import a vendor agent SDK directly.
 */

export const agentRunStateSchema = z.object({
  runId: z.string(),
  workerId: z.string(),
  status: z.enum([
    "pending",
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
  ]),
  currentNode: z.string().nullable(),
  approvalRequestId: z.string().nullable(),
  updatedAt: z.string(),
});

export type AgentRunState = z.infer<typeof agentRunStateSchema>;

export interface StartRunInput {
  workerId: string;
  input: Record<string, unknown>;
}

export interface AgentUiAdapter {
  /** Start a new worker run and return its id. */
  startRun(input: StartRunInput): Promise<string>;
  /** Read the current run state. */
  getRunState(runId: string): Promise<AgentRunState>;
  /** Subscribe to state changes; returns an unsubscribe function. */
  onRunStateChange(
    runId: string,
    listener: (state: AgentRunState) => void,
  ): () => void;
  /** Resume a run waiting on approval with the human decision. */
  resumeRun(
    runId: string,
    decision: { approved: boolean; comment?: string },
  ): Promise<void>;
}
