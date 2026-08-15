import { describe, expect, it } from "vitest";

// Mirrors the naming helpers in FactoryPage so the client-side name shown to the
// user matches what the server writes.
function extensionOf(filename: string): string {
  return filename.match(/\.[^.]+$/)?.[0].toLowerCase() ?? "";
}

function alreadyHasExtension(name: string, extension: string): boolean {
  return extension !== "" && name.toLowerCase().endsWith(extension);
}

function withExtension(name: string, extension: string): string {
  if (!extension || alreadyHasExtension(name, extension)) {
    return name;
  }
  return `${name.replace(/\.[^.]+$/, "")}${extension}`;
}

describe("result file naming", () => {
  it("does not double an extension the user already typed", () => {
    expect(withExtension("IMG_0118.HEIC", extensionOf("donor.heic"))).toBe("IMG_0118.HEIC");
    expect(withExtension("IMG_0118.heic", extensionOf("donor.HEIC"))).toBe("IMG_0118.heic");
  });

  it("appends when the name has no extension", () => {
    expect(withExtension("IMG_0118", ".heic")).toBe("IMG_0118.heic");
  });

  it("replaces a different extension rather than stacking one", () => {
    // Must match the server's normalize_output_name, which has the final say.
    expect(withExtension("IMG_0118.jpg", ".heic")).toBe("IMG_0118.heic");
    expect(withExtension("my.heic.photo", ".heic")).toBe("my.heic.heic");
  });

  it("hides the suffix chip only when the extension is already present", () => {
    expect(alreadyHasExtension("IMG_0118.HEIC", ".heic")).toBe(true);
    expect(alreadyHasExtension("IMG_0118", ".heic")).toBe(false);
    expect(alreadyHasExtension("", ".heic")).toBe(false);
  });
});
