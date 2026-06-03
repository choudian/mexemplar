import { afterEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi, requestJson } from "../../src/api/client";

describe("api client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    configureDesktopApi({ baseUrl: "", sessionToken: "" });
  });

  test("preserves non-json error response text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(
        "<html><body><h1>502 Bad Gateway</h1><p>Proxy unavailable</p></body></html>",
        { status: 502, headers: { "Content-Type": "text/html" } },
      )),
    );
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });

    await expect(requestJson("/api/bootstrap")).rejects.toMatchObject({
      name: "DesktopApiError",
      status: 502,
      code: "desktop_api_error",
      message: "502 Bad Gateway Proxy unavailable",
      details: {
        responseText: expect.stringContaining("Proxy unavailable"),
      },
    });
  });
});
