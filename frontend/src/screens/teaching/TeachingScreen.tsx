import { useEffect } from "react";

import { useTeachingStore } from "../../state/teachingStore";
import IntentStage from "./IntentStage";
import LearningStage from "./LearningStage";
import RecordingModePicker from "./RecordingModePicker";
import RecordingStage from "./RecordingStage";
import TrialStage from "./TrialStage";
import type { TeachingRun, TeachingStage } from "../../api/teaching";

const teachingSteps = [
  { id: "selecting", label: "选择方式" },
  { id: "recording", label: "操作录制" },
  { id: "intent_confirmation", label: "意图理解" },
  { id: "learning", label: "技能学习" },
  { id: "trial_validation", label: "技能试用" },
] as const;

function normalizeStage(stage: string): (typeof teachingSteps)[number]["id"] {
  if (stage === "published" || stage === "failed" || stage === "abandoned") {
    return "trial_validation";
  }
  return teachingSteps.some((step) => step.id === stage) ? (stage as (typeof teachingSteps)[number]["id"]) : "selecting";
}

function displayStageFor(run: TeachingRun | null, stage: TeachingStage) {
  if (run && stage === "selecting") {
    return "recording";
  }
  return normalizeStage(stage);
}

function TeachingStepper({ stage }: { stage: string }): JSX.Element {
  const normalized = normalizeStage(stage);
  const activeIndex = teachingSteps.findIndex((step) => step.id === normalized);
  return (
    <div className="teaching-stepper" aria-label="教学流程">
      {teachingSteps.map((step, index) => {
        const done = index < activeIndex;
        const active = index === activeIndex;
        return (
          <div className="teaching-stepper-item" data-active={active} data-done={done} key={step.id}>
            <span>{done ? "✓" : index + 1}</span>
            <strong>{step.label}</strong>
            {index < teachingSteps.length - 1 ? <i aria-hidden="true" /> : null}
          </div>
        );
      })}
    </div>
  );
}

export function TeachingScreen(): JSX.Element {
  const readiness = useTeachingStore((state) => state.readiness);
  const selectedMode = useTeachingStore((state) => state.selectedMode);
  const run = useTeachingStore((state) => state.run);
  const stage = useTeachingStore((state) => state.stage);
  const intentReply = useTeachingStore((state) => state.intentReply);
  const progressLog = useTeachingStore((state) => state.progressLog);
  const busy = useTeachingStore((state) => state.busy);
  const lastError = useTeachingStore((state) => state.lastError);
  const loadReadiness = useTeachingStore((state) => state.loadReadiness);
  const setSelectedMode = useTeachingStore((state) => state.setSelectedMode);
  const createRun = useTeachingStore((state) => state.createRun);
  const startRecording = useTeachingStore((state) => state.startRecording);
  const stopRecording = useTeachingStore((state) => state.stopRecording);
  const decideDesktopHealth = useTeachingStore((state) => state.decideDesktopHealth);
  const setIntentReply = useTeachingStore((state) => state.setIntentReply);
  const replyIntent = useTeachingStore((state) => state.replyIntent);
  const confirmIntent = useTeachingStore((state) => state.confirmIntent);
  const startTrial = useTeachingStore((state) => state.startTrial);

  useEffect(() => {
    void loadReadiness();
  }, [loadReadiness]);

  const displayStage = displayStageFor(run, stage);

  return (
    <section className="teaching-screen" aria-label="技能教学">
      <div className="teaching-header">
        <div>
          <h2>技能教学</h2>
          <p>演示一遍你想自动化的操作，系统会学会并替你执行。</p>
        </div>
      </div>
      <TeachingStepper stage={displayStage} />
      <div className="teaching-workflow me-scroll" data-stage={stage}>
        {!run ? (
          <RecordingModePicker
            modes={readiness}
            selectedMode={selectedMode}
            busy={busy}
            onSelect={setSelectedMode}
            onCreate={(mode) => {
              void createRun(mode);
            }}
          />
        ) : null}
        {run && displayStage === "recording" ? (
          <RecordingStage
            run={run}
            busy={busy}
            progressLog={progressLog}
            onStart={() => {
              void startRecording();
            }}
            onStop={() => {
              void stopRecording();
            }}
            onDesktopDecision={(decision) => {
              void decideDesktopHealth(decision);
            }}
          />
        ) : null}
        {run && displayStage === "intent_confirmation" ? (
          <IntentStage
            value={intentReply}
            disabled={busy || !run || stage !== "intent_confirmation"}
            onChange={setIntentReply}
            onReply={() => {
              void replyIntent();
            }}
            onConfirm={() => {
              void confirmIntent();
            }}
          />
        ) : null}
        {run && displayStage === "learning" ? (
          <LearningStage
            active={stage === "learning"}
            progressLog={progressLog}
            onStartTrial={() => {
              void startTrial();
            }}
          />
        ) : null}
        {run && displayStage === "trial_validation" ? (
          <TrialStage
            active={stage === "trial_validation"}
            disabled={busy || !run || ["selecting", "recording", "intent_confirmation"].includes(stage)}
            onStart={() => {
              void startTrial();
            }}
          />
        ) : null}
      </div>
      {lastError ? <div className="teaching-error">{lastError}</div> : null}
    </section>
  );
}

export default TeachingScreen;
