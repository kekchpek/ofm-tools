import { apiFetch, downloadUrl } from "./api/client";

/**
 * Saving a result on mobile.
 *
 * A web page cannot write to the iOS photo library — there is no API for it.
 * What it can do is hand the file to the system share sheet, which offers
 * "Save Image" / "Save Video", and those write to Photos. That only appears
 * when the file carries a real image/video MIME type, so the download endpoint
 * sends one rather than application/octet-stream.
 *
 * Everywhere else (and whenever sharing is unavailable or declined) this falls
 * back to an ordinary download.
 */

const MIME_BY_EXTENSION: Record<string, string> = {
  mp4: "video/mp4",
  m4v: "video/x-m4v",
  mov: "video/quicktime",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  heic: "image/heic",
  heif: "image/heif",
};

function mimeFor(filename: string): string {
  const extension = filename.split(".").pop()?.toLowerCase() ?? "";
  return MIME_BY_EXTENSION[extension] ?? "application/octet-stream";
}

/** Whether this browser can share actual files, not just links. */
export function canShareFiles(): boolean {
  if (typeof navigator === "undefined" || !navigator.canShare || !navigator.share) {
    return false;
  }
  try {
    const probe = new File([new Blob([new Uint8Array(1)])], "probe.jpg", { type: "image/jpeg" });
    return navigator.canShare({ files: [probe] });
  } catch {
    return false;
  }
}

export function triggerDownload(fileId: string, filename: string): void {
  const link = document.createElement("a");
  link.href = downloadUrl(fileId);
  link.download = filename;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function fetchAsFile(fileId: string, filename: string): Promise<File> {
  // Credentialed: results are private to the OFM.
  const response = await apiFetch(`/api/v1/files/${fileId}/download`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const blob = await response.blob();
  const type = blob.type && blob.type !== "application/octet-stream" ? blob.type : mimeFor(filename);
  return new File([blob], filename, { type });
}

export type SaveOutcome = "shared" | "downloaded" | "cancelled";

/**
 * Offer the share sheet, falling back to a download.
 *
 * Must be called from a user gesture. iOS can reject `share()` if too long
 * passes between the tap and the call, so a failure here quietly degrades to a
 * download rather than surfacing an error.
 */
export async function saveFile(fileId: string, filename: string): Promise<SaveOutcome> {
  if (!canShareFiles()) {
    triggerDownload(fileId, filename);
    return "downloaded";
  }

  let file: File;
  try {
    file = await fetchAsFile(fileId, filename);
  } catch {
    triggerDownload(fileId, filename);
    return "downloaded";
  }

  if (!navigator.canShare({ files: [file] })) {
    triggerDownload(fileId, filename);
    return "downloaded";
  }

  try {
    await navigator.share({ files: [file] });
    return "shared";
  } catch (error) {
    // The user dismissing the sheet is not a failure worth reporting.
    if (error instanceof DOMException && error.name === "AbortError") {
      return "cancelled";
    }
    triggerDownload(fileId, filename);
    return "downloaded";
  }
}
