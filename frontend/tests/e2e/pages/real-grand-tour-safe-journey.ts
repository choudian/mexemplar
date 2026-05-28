import type { Page } from "@playwright/test";

export const SAFE_LIVE_JOURNEY = {
  liveJourneyId: "safe-local-form-v1",
  targetFixtureIdentity: "mexemplar-real-tour-local-fixture-form-v1",
  fixturePath: "/real-grand-tour-safe-fixture.html",
  fixedInputText: "Sample approval request for local validation only",
  terminalAssertion: "Submitted",
  actions: ["focus-request-field", "enter-fixed-text", "submit-form", "observe-terminal-state"],
} as const;

export class RealGrandTourSafeJourneyPage {
  constructor(private readonly page: Page) {}

  async openFixture(baseUrl?: string): Promise<void> {
    if (baseUrl) {
      await this.page.goto(new URL(SAFE_LIVE_JOURNEY.fixturePath, baseUrl).toString());
      return;
    }

    await this.page.setContent(`
      <main>
        <h1>${SAFE_LIVE_JOURNEY.targetFixtureIdentity}</h1>
        <label>
          Request
          <input aria-label="Request" />
        </label>
        <button type="button" onclick="document.body.dataset.done='1'; document.querySelector('#status').textContent='Submitted'">Submit</button>
        <p id="status">Ready</p>
      </main>
    `);
  }

  async performFixedActions(): Promise<void> {
    await this.page.getByLabel("Request").fill(SAFE_LIVE_JOURNEY.fixedInputText);
    await this.page.getByRole("button", { name: "Submit" }).click();
  }

  async terminalState(): Promise<string> {
    return this.page.locator("#status").innerText();
  }
}
