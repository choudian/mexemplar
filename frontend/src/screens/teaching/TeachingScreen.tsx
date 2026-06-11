import { ArrowRight, CheckCircle2, RotateCcw } from "lucide-react";
import { useEffect } from "react";

import { Button } from "../../components/primitives";
import type { TeachingRun, TeachingStage } from "../../api/teaching";
import { useShellStore } from "../../state/shellStore";
import { useSkillsStore } from "../../state/skillsStore";
import { resetToSelecting, useTeachingStore } from "../../state/teachingStore";
import IntentStage from "./IntentStage";
import LearningStage from "./LearningStage";
import RecordingModePicker from "./RecordingModePicker";
import RecordingStage from "./RecordingStage";

const SKILL_LIST_PATH = "/tools/list";

const teachingSteps = [
  { id: "selecting", label: "选择方式" },
  { id: "recording", label: "操作录制" },
  { id: "intent_confirmation", label: "意图理解" },
  { id: "learning", label: "工具学习" },
  { id: "learned", label: "学习完成" },
] as const;

function normalizeStage(stage: string): (typeof teachingSteps)[number]["id"] {
  if (stage === "trial_validation" || stage === "published") {
    return "learned";
  }
  if (stage === "failed") {
    return "learning";
  }
  if (stage === "abandoned") {
    return "recording";
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

function LearnedStage(): JSX.Element {
  const openSkillList = () => {
    useSkillsStore.getState().setCategory("pending");
    if (window.location.pathname !== SKILL_LIST_PATH) {
      window.history.pushState({}, "", SKILL_LIST_PATH);
      window.dispatchEvent(new Event("popstate"));
    }
    useShellStore.getState().setRoute("skills");
  };

  return (
    <section className="teaching-learning-card" aria-labelledby="teaching-learned-heading">
      <div className="teaching-learning-hero">
        <div className="teaching-learning-orbit">
          <CheckCircle2 size={30} strokeWidth={2.2} />
        </div>
        <h3 id="teaching-learned-heading">工具学习完成</h3>
        <p>新工具已进入工具列表。后续试用从工具列表发起，不在教学页继续。</p>
      </div>

      <div className="teaching-learning-hint">
        到工具列表的「待考核」工具中选择它进行试用。
      </div>

      <div className="teaching-learning-actions">
        <p>教学页只负责录制和学习；验证、继续试用和发布状态都在工具列表里完成。</p>
        <Button kind="primary" onClick={openSkillList}>
          <span>去工具列表试用</span>
          <ArrowRight size={14} />
        </Button>
      </div>
    </section>
  );
}

export function TeachingScreen(): JSX.Element {
  const readiness = useTeachingStore((state) => state.readiness);
  const selectedMode = useTeachingStore((state) => state.selectedMode);
  const run = useTeachingStore((state) => state.run);
  const stage = useTeachingStore((state) => state.stage);
  const progressLog = useTeachingStore((state) => state.progressLog);
  const busy = useTeachingStore((state) => state.busy);
  const loadReadiness = useTeachingStore((state) => state.loadReadiness);
  const setSelectedMode = useTeachingStore((state) => state.setSelectedMode);
  const createRun = useTeachingStore((state) => state.createRun);
  const startRecording = useTeachingStore((state) => state.startRecording);
  const stopRecording = useTeachingStore((state) => state.stopRecording);
  const decideDesktopHealth = useTeachingStore((state) => state.decideDesktopHealth);

  useEffect(() => {
    void loadReadiness();
  }, [loadReadiness]);

  const displayStage = displayStageFor(run, stage);

  return (
    <section className="teaching-screen" aria-label="工具教学">
      <div className="teaching-header">
        <div>
          <h2>工具教学</h2>
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

      {displayStage === "intent_confirmation" ? (
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
          {run && displayStage === "learned" ? <LearnedStage /> : null}
        </div>
      )}
    </section>
  );
}

export default TeachingScreen;
