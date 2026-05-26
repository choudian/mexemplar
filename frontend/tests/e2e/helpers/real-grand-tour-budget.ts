export type BudgetStatus = "ok" | "budget_exceeded";

export class RealGrandTourBudget {
  private paidCalls = 0;
  private readonly startedAt: number;

  constructor(
    private readonly maxElapsedMs: number,
    private readonly maxPaidCalls: number,
    now: () => number = Date.now,
  ) {
    this.startedAt = now();
    this.now = now;
  }

  private readonly now: () => number;

  recordPaidCall(count = 1): BudgetStatus {
    this.paidCalls += Math.max(0, count);
    return this.status();
  }

  status(): BudgetStatus {
    if (this.elapsedMs() > this.maxElapsedMs) return "budget_exceeded";
    if (this.paidCalls > this.maxPaidCalls) return "budget_exceeded";
    return "ok";
  }

  elapsedMs(): number {
    return Math.max(0, this.now() - this.startedAt);
  }

  usage(): { elapsedMs: number; paidCallCount: number } {
    return { elapsedMs: this.elapsedMs(), paidCallCount: this.paidCalls };
  }
}
