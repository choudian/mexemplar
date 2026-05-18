import { useEffect } from "react";

import { useTeachingStore, resetToSelecting } from "../../state/teachingStore";
import { useShellStore } from "../../state/shellStore";
import IntentStage from "./IntentStage";
import LearningStage from "./LearningStage";
import RecordingModePicker from "./RecordingModePicker";
import RecordingStage from "./RecordingStage";
import type { TeachingRun, TeachingStage } from "../../api/teaching";
import { Button } from "../../components/primitives";
import { RotateCcw } from "lucide-react";

const LEARNING_REDIRECT_MS = 3000;

const teachingSteps = [
  { id: "selecting", label: "选择方式" },
  { id: "recording", label: "操作录制" },
  { id: "intent_confirmation", label: "意图理解" },
  { id: "learning", label: "技能学习" },
] as const;

function normalizeStage(stage: string): (typeof teachingSteps)[number]["id"] {
  if (stage === "published" || stage === "failed" || stage === "abandoned" || stage === "trial_validation") {
    return "learning";
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
  const progressLog = useTeachingStore((state) => state.progressLog);
  const busy = useTeachingStore((state) => state.busy);
  const lastError = useTeachingStore((state) => state.lastError);
  const loadReadiness = useTeachingStore((state) => state.loadReadiness);
  const setSelectedMode = useTeachingStore((state) => state.setSelectedMode);
  const createRun = useTeachingStore((state) => state.createRun);
  const startRecording = useTeachingStore((state) => state.startRecording);
  const stopRecording = useTeachingStore((state) => state.stopRecording);
  const decideDesktopHealth = useTeachingStore((state) => state.decideDesktopHealth);

  useEffect(() => {
    void loadReadiness();
  }, [loadReadiness]);

  useEffect(() => {
    if (stage !== "learning") return;
    const timer = setTimeout(() => {
      useShellStore.getState().setRoute("assistant");
    }, LEARNING_REDIRECT_MS);
    return () => clearTimeout(timer);
  }, [stage]);

  const displayStage = displayStageFor(run, stage);
  const isChatStage = displayStage === "intent_confirmation";

  return (
    <section className="teaching-screen" aria-label="技能教学">
      <div className="teaching-header">
        <div>
          <h2>技能教学</h2>
          <p>演示一遍你想自动化的操作，系统会学会并替你执行。</p>
        </div>
        {stage !== "selecting" ? (
          <Button
            kind="ghost"
            onClick={() => {
              useTeachingStore.setState(resetToSelecting());
            }}
          >
            <RotateCcw size={14} />
            <span>重新开始</span>
          </Button>
        ) : null}
      </div>
      <TeachingStepper stage={displayStage} />

      {isChatStage ? (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
          {run && displayStage === "intent_confirmation" ? <IntentStage /> : null}
        </div>
      ) : (
        <div className="teaching-workflow me-scroll" data-stage={stage}>
          {!run ? (
            <RecordingModePicker
              busy={busy}
              modes={readiness}
              onCreate={(mode) => {
                void createRun(mode);
              }}
              onSelect={setSelectedMode}
              selectedMode={selectedMode}
            />
          ) : null}
          {run && displayStage === "recording" ? (
            <RecordingStage
              busy={busy}
              onDesktopDecision={(decision) => {
                void decideDesktopHealth(decision);
              }}
              onStart={() => {
                void startRecording();
              }}
              onStop={() => {
                void stopRecording();
              }}
              progressLog={progressLog}
              run={run}
            />
          ) : null}
          {run && displayStage === "learning" ? (
            <LearningStage
              active={stage === "learning"}
              progressLog={progressLog}
            />
          ) : null}
        </div>
      )}
      {lastError ? <div className="teaching-error">{lastError}</div> : null}
    </section>
  );
}

export default TeachingScreen;
