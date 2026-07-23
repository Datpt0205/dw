import type { AgentRunState, AgentUiAdapter, StartRunInput } from "./adapter";

/**
 * Working in-memory adapter used in tests and as the vendor-free fallback.
 * Simulates the run lifecycle: running → waiting_approval → completed/cancelled.
 */
export class MockAgentUiAdapter implements AgentUiAdapter {
  private readonly runs = new Map<string, AgentRunState>();
  private readonly listeners = new Map<
    string,
    Set<(state: AgentRunState) => void>
  >();
  private counter = 0;

  async startRun(input: StartRunInput): Promise<string> {
    const runId = `mock-run-${++this.counter}`;
    this.setState({
      runId,
      workerId: input.workerId,
      status: "waiting_approval",
      currentNode: "HUMAN_REVIEW",
      approvalRequestId: `mock-approval-${this.counter}`,
      updatedAt: new Date().toISOString(),
    });
    return runId;
  }

  async getRunState(runId: string): Promise<AgentRunState> {
    const state = this.runs.get(runId);
    if (!state) throw new Error(`unknown run: ${runId}`);
    return state;
  }

  onRunStateChange(
    runId: string,
    listener: (state: AgentRunState) => void,
  ): () => void {
    const set = this.listeners.get(runId) ?? new Set();
    set.add(listener);
    this.listeners.set(runId, set);
    return () => {
      set.delete(listener);
    };
  }

  async resumeRun(
    runId: string,
    decision: { approved: boolean; comment?: string },
  ): Promise<void> {
    const state = await this.getRunState(runId);
    if (state.status !== "waiting_approval") {
      throw new Error(`run ${runId} is not waiting for approval`);
    }
    this.setState({
      ...state,
      status: decision.approved ? "completed" : "cancelled",
      currentNode: null,
      approvalRequestId: null,
      updatedAt: new Date().toISOString(),
    });
  }

  private setState(state: AgentRunState): void {
    this.runs.set(state.runId, state);
    for (const listener of this.listeners.get(state.runId) ?? []) {
      listener(state);
    }
  }
}
