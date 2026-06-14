import fs from "node:fs";
import path from "node:path";

export interface ScenarioReport {
  scenarioId: string;
  status: "passed" | "failed" | "skipped";
  lastObservableState: string;
  paidCallCount: number;
  elapsedMs: number;
  cleanupStatus: string;
  reason?: string;
}

export interface RealGrandTourSummaryReport {
  runId: string;
  commitSha: string;
  liveJourneyId: string;
  startedAt: string;
  finishedAt: string;
  budgetUsage: { elapsedMs: number; paidCallCount: number };
  scenarios: ScenarioReport[];
}

const FORBIDDEN_PATTERNS = [
  /sk-[A-Za-z0-9_-]{8,}/,
  /MEXEMPLAR_DESKTOP_TOKEN/i,
  /data:(?:image|audio|video)\/[a-z0-9.+-]+;base64,/i,
  /\b(prompt|response|credential|api[_-]?key|password|secret|token)\s*[:=]/i,
];

export function assertSanitizedArtifact(value: unknown, extraSentinels: string[] = []): void {
  const text = JSON.stringify(value);
  for (const sentinel of extraSentinels.filter(Boolean)) {
    if (text.includes(sentinel)) throw new Error(`unsanitized_sentinel:${sentinel}`);
  }
  for (const pattern of FORBIDDEN_PATTERNS) {
    if (pattern.test(text)) throw new Error("unsanitized_artifact");
  }
}

export function writeSummaryReport(
  report: RealGrandTourSummaryReport,
  outputDir: string,
  extraSentinels: string[] = [],
): string {
  assertSanitizedArtifact(report, extraSentinels);
  fs.mkdirSync(outputDir, { recursive: true });
  const file = path.join(outputDir, `${report.runId}.summary.json`);
  fs.writeFileSync(file, `${JSON.stringify(report, null, 2)}\n`, "utf-8");
  return file;
}
