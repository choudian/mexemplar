export async function withLiveRecordingCleanup<T>(
  runScenario: (markStopRequired: () => void) => Promise<T>,
  stopRecording: () => Promise<void>,
): Promise<T> {
  let stopRequired = false;
  let result!: T;
  let scenarioError: unknown;
  let cleanupFailed = false;
  try {
    result = await runScenario(() => {
      stopRequired = true;
    });
  } catch (error) {
    scenarioError = error;
  } finally {
    if (stopRequired) {
      try {
        await stopRecording();
      } catch {
        cleanupFailed = true;
      }
    }
  }
  if (cleanupFailed) {
    throw new Error(
      scenarioError
        ? "recording_cleanup_failed_after_scenario_failure"
        : "recording_cleanup_failed",
    );
  }
  if (scenarioError) {
    throw scenarioError;
  }
  return result;
}
