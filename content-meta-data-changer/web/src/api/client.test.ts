import { afterEach, describe, expect, it, vi } from "vitest";
import { createSession, getAuthConfig } from "./client";

const originalFetch = globalThis.fetch;

function htmlResponse() {
  return new Response("<!doctype html><html><body>app</body></html>", {
    status: 200,
    headers: { "content-type": "text/html" },
  });
}

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("API error reporting", () => {
  it("explains VITE_API_BASE when the SPA rewrite answers with HTML", async () => {
    // Cloudflare Pages serves index.html with HTTP 200 for unknown paths, so a
    // missing VITE_API_BASE looks like a successful response.
    // A fresh Response per call: a body can only be read once.
    globalThis.fetch = vi.fn().mockImplementation(() => Promise.resolve(htmlResponse()));

    await expect(getAuthConfig()).rejects.toThrow(/VITE_API_BASE/);
    await expect(getAuthConfig()).rejects.toThrow(/HTML page instead of JSON/);
  });

  it("explains CORS when the request cannot be made at all", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(createSession()).rejects.toThrow(/CORS_ORIGINS/);
  });

  it("passes through a normal JSON response", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(jsonResponse({ session_id: "abc" }));

    await expect(createSession()).resolves.toBe("abc");
  });
});
