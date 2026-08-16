import { afterEach, describe, expect, it, vi } from "vitest";

// navigator is a getter on globalThis in Node, so it needs stubGlobal.
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.resetModules();
});

function stubNavigator(options: { share?: unknown; canShare?: unknown }) {
  vi.stubGlobal("navigator", options);
}

describe("canShareFiles", () => {
  it("is false when the browser has no share API", async () => {
    stubNavigator({});
    const { canShareFiles } = await import("./saveFile");
    expect(canShareFiles()).toBe(false);
  });

  it("is false when the browser shares links but not files", async () => {
    stubNavigator({ share: () => Promise.resolve(), canShare: () => false });
    const { canShareFiles } = await import("./saveFile");
    expect(canShareFiles()).toBe(false);
  });

  it("is true when the browser can share files", async () => {
    stubNavigator({ share: () => Promise.resolve(), canShare: () => true });
    const { canShareFiles } = await import("./saveFile");
    expect(canShareFiles()).toBe(true);
  });
});

describe("saveFile", () => {
  it("shares the file when the browser supports it", async () => {
    const share = vi.fn().mockResolvedValue(undefined);
    stubNavigator({ share, canShare: () => true });
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(new Blob([new Uint8Array([1, 2, 3])], { type: "image/heic" }), { status: 200 }),
    );

    const { saveFile } = await import("./saveFile");
    await expect(saveFile("file-1", "beach.heic")).resolves.toBe("shared");

    const shared = share.mock.calls[0][0].files[0] as File;
    expect(shared.name).toBe("beach.heic");
    // The MIME type is what makes iOS offer "Save Image".
    expect(shared.type).toBe("image/heic");
  });

  it("reports a dismissed share sheet as cancelled, not a failure", async () => {
    const share = vi.fn().mockRejectedValue(new DOMException("cancelled", "AbortError"));
    stubNavigator({ share, canShare: () => true });
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(new Blob([new Uint8Array([1])], { type: "image/jpeg" }), { status: 200 }),
    );

    const { saveFile } = await import("./saveFile");
    await expect(saveFile("file-1", "x.jpg")).resolves.toBe("cancelled");
  });

  it("falls back to a download when sharing is unavailable", async () => {
    stubNavigator({});
    const click = vi.fn();
    const link: Record<string, unknown> = { click, remove: vi.fn(), style: {} };
    vi.stubGlobal("document", {
      createElement: () => link,
      body: { appendChild: vi.fn() },
    });

    const { saveFile } = await import("./saveFile");
    await expect(saveFile("file-1", "x.mov")).resolves.toBe("downloaded");
    expect(click).toHaveBeenCalled();
    expect(link.download).toBe("x.mov");
  });
});
