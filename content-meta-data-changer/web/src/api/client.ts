export type Segment = {
  offset: number;
  size: number;
  end: number;
  label: string;
  category: string;
  path: string[];
  path_label: string;
  edit_safety: {
    level: string;
    label: string;
    reason: string;
    mark: string;
  };
};

export type LayoutResult = {
  file_size: number;
  segments: Segment[];
  summary: Record<string, number>;
};

export type MetadataResult = {
  filename: string;
  format_label: string;
  file_size: number;
  media_kind: "video" | "image" | "unknown";
  text: string;
};

export type StoredFile = {
  file_id: string;
  session_id: string;
  filename: string;
  size: number;
  media_kind: string;
};

export type JobResult = {
  id: string;
  type: "transfer" | "convert" | "update_preview" | "factory";
  status: "queued" | "running" | "succeeded" | "failed";
  error: string | null;
  output_file_id: string | null;
};

export type User = {
  id: string;
  email: string;
  name: string;
  picture_url: string | null;
};

export type AuthConfig = {
  enabled: boolean;
  login_url: string | null;
};

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

function fetchOptions(init?: RequestInit): RequestInit {
  return {
    credentials: "include",
    ...init,
    headers: init?.headers,
  };
}

/**
 * fetch() with deployment-aware error messages.
 *
 * A misconfigured deploy fails in two ways that are invisible by default:
 * a blocked cross-origin request rejects with a bare "Failed to fetch", and a
 * missing VITE_API_BASE sends API calls back to the frontend host, where the
 * SPA rewrite answers with index.html and HTTP 200.
 */
function currentOrigin(): string {
  return typeof window === "undefined" ? "this site's origin" : window.location.origin;
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const url = `${API_BASE}${path}`;
  try {
    return await fetch(url, fetchOptions(init));
  } catch (cause) {
    throw new Error(
      `Could not reach the API at ${url}. ` +
        `This is normally a CORS or network problem — check that CORS_ORIGINS on the API ` +
        `includes ${currentOrigin()}, and that the API is reachable over HTTPS. (${cause})`,
    );
  }
}

async function readJson<T>(response: Response, url: string): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json() as Promise<T>;
  }
  const body = await response.text();
  if (body.trimStart().startsWith("<")) {
    throw new Error(
      `${url} returned an HTML page instead of JSON. The app is calling itself rather than ` +
        `the API — set VITE_API_BASE to the API URL and rebuild (Vite bakes it in at build time, ` +
        `so changing the variable alone is not enough).`,
    );
  }
  throw new Error(`${url} returned "${contentType || "no content type"}" instead of JSON.`);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  return readJson<T>(response, `${API_BASE}${path}`);
}

export async function getAuthConfig(): Promise<AuthConfig> {
  return request<AuthConfig>("/api/v1/auth/config");
}

export async function getCurrentUser(): Promise<User | null> {
  const response = await apiFetch("/api/v1/auth/me");
  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return readJson<User>(response, `${API_BASE}/api/v1/auth/me`);
}

export function loginUrl(returnPath = "/"): string {
  const returnUrl = `${window.location.origin}${returnPath}`;
  return `${API_BASE}/api/v1/auth/google?return_url=${encodeURIComponent(returnUrl)}`;
}

export async function logout(): Promise<void> {
  await request("/api/v1/auth/logout", { method: "POST" });
}

export async function createSession(): Promise<string> {
  const data = await request<{ session_id: string }>("/api/v1/sessions", { method: "POST" });
  return data.session_id;
}

export async function uploadFile(sessionId: string, file: File): Promise<StoredFile> {
  const form = new FormData();
  form.append("file", file);
  const path = `/api/v1/sessions/${sessionId}/files`;
  const response = await apiFetch(path, { method: "POST", body: form });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return readJson<StoredFile>(response, `${API_BASE}${path}`);
}

export function getMetadata(fileId: string): Promise<MetadataResult> {
  return request(`/api/v1/files/${fileId}/metadata`);
}

export function getLayout(fileId: string): Promise<LayoutResult> {
  return request(`/api/v1/files/${fileId}/layout`);
}

export function previewUrl(fileId: string): string {
  return `${API_BASE}/api/v1/files/${fileId}/preview.jpg`;
}

export function downloadUrl(fileId: string): string {
  return `${API_BASE}/api/v1/files/${fileId}/download`;
}

export async function getSegmentBytes(fileId: string, offset: number): Promise<{ hex: string; text: string }> {
  return request(`/api/v1/files/${fileId}/segments/${offset}?limit=512`);
}

export async function getUnknownHeaders(fileId: string): Promise<string> {
  const data = await request<{ text: string }>(`/api/v1/files/${fileId}/unknown-headers`);
  return data.text;
}

export async function getUnknownMemory(fileId: string): Promise<string> {
  const data = await request<{ text: string }>(`/api/v1/files/${fileId}/unknown-memory`);
  return data.text;
}

export async function startTransferJob(
  targetFileId: string,
  sourceFileId: string,
  outputFilename: string,
): Promise<JobResult> {
  return request("/api/v1/jobs/transfer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_file_id: targetFileId,
      source_file_id: sourceFileId,
      output_filename: outputFilename,
    }),
  });
}

export async function startUpdatePreviewJob(sourceFileId: string, outputFilename: string): Promise<JobResult> {
  return request("/api/v1/jobs/update-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_file_id: sourceFileId,
      output_filename: outputFilename,
    }),
  });
}

export async function startConvertJob(
  sourceFileId: string,
  outputFilename: string,
  target: string,
): Promise<JobResult> {
  return request("/api/v1/jobs/convert", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_file_id: sourceFileId,
      output_filename: outputFilename,
      target,
    }),
  });
}

/**
 * OFM Factory: payload from the source file, format and metadata from the donor.
 * Omit outputFilename to let the server name it `<source>_ofm<donor-ext>`.
 */
export async function startFactoryJob(
  sourceFileId: string,
  metadataFileId: string,
  outputFilename?: string,
): Promise<JobResult> {
  return request("/api/v1/jobs/factory", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_file_id: sourceFileId,
      metadata_file_id: metadataFileId,
      ...(outputFilename ? { output_filename: outputFilename } : {}),
    }),
  });
}

export async function getJob(jobId: string): Promise<JobResult> {
  return request(`/api/v1/jobs/${jobId}`);
}

export async function pollJob(jobId: string): Promise<JobResult> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const job = await getJob(jobId);
    if (job.status === "succeeded" || job.status === "failed") {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("Job timed out");
}

export type ContentPiece = {
  id: string;
  name: string;
  output_stem: string;
  source_file_id: string | null;
  metadata_file_id: string | null;
  result_file_id: string | null;
  result_filename: string | null;
  position: number;
  created_at: string;
  updated_at: string;
  source_file: StoredFile | null;
  metadata_file: StoredFile | null;
  result_file: StoredFile | null;
};

export type PiecePatch = Partial<{
  name: string;
  output_stem: string;
  source_file_id: string;
  metadata_file_id: string;
  result_file_id: string;
  result_filename: string;
  position: number;
  /** Names of fields to null out — a JSON null cannot express this. */
  clear: string[];
}>;

export type StorageUsage = {
  used_bytes: number;
  quota_bytes: number;
};

export function listPieces(): Promise<ContentPiece[]> {
  return request<ContentPiece[]>("/api/v1/pieces");
}

export function createPiece(name: string): Promise<ContentPiece> {
  return request<ContentPiece>("/api/v1/pieces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function updatePiece(pieceId: string, patch: PiecePatch): Promise<ContentPiece> {
  return request<ContentPiece>(`/api/v1/pieces/${pieceId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function deletePiece(pieceId: string): Promise<void> {
  const response = await apiFetch(`/api/v1/pieces/${pieceId}`, { method: "DELETE" });
  if (!response.ok && response.status !== 404) {
    throw new Error(await response.text());
  }
}

export function getStorageUsage(): Promise<StorageUsage> {
  return request<StorageUsage>("/api/v1/storage");
}
