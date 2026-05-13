import { useEffect } from "react";

import { useTeachingStore } from "../../state/teachingStore";
import IntentStage from "./IntentStage";
import LearningStage from "./LearningStage";
import RecordingModePicker from "./RecordingModePicker";
import RecordingStage from "./RecordingStage";
import TrialStage from "./TrialStage";

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

  return (
    <section className="teaching-screen" aria-label="技能教学">
      <div className="teaching-header">
        <h2>技能教学</h2>
        <p>选择录制方式，完成演示、意图确认、学习和试用验证。</p>
      </div>
      <RecordingModePicker
        modes={readiness}
        selectedMode={selectedMode}
        busy={busy}
        onSelect={setSelectedMode}
        onCreate={(mode) => {
          void createRun(mode);
        }}
      />
      <div className="teaching-workflow" data-stage={stage}>
        <RecordingStage
          run={run}
          busy={busy}
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
        <LearningStage active={stage === "learning"} progressLog={progressLog} />
        <TrialStage
          active={stage === "trial_validation"}
          disabled={busy || !run || stage !== "trial_validation"}
          onStart={() => {
            void startTrial();
          }}
        />
      </div>
      {lastError ? <div className="teaching-error">{lastError}</div> : null}
    </section>
  );
}

export default TeachingScreen;
