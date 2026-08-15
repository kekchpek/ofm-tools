import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  downloadUrl,
  getLayout,
  getMetadata,
  getUnknownHeaders,
  getUnknownMemory,
  loginUrl,
  pollJob,
  previewUrl,
  startConvertJob,
  startUpdatePreviewJob,
  uploadFile,
  type LayoutResult,
  type MetadataResult,
  type Segment,
  type StoredFile,
} from "./api/client";
import AppHeader from "./AppHeader";
import ConnectionError from "./ConnectionError";
import MemoryLayoutPanel from "./MemoryLayoutPanel";
import TransferMetadataModal from "./TransferMetadataModal";
import { useSession } from "./useSession";

const VIDEO_CONVERT_TARGETS = ["mp4", "mov", "mkv", "webm"];
const IMAGE_CONVERT_TARGETS = ["jpg", "png", "heic"];

type AppProps = {
  files?: StoredFile[];
};

export default function App() {
  const navigate = useNavigate();
  const { fileId } = useParams();
  const { authReady, authRequired, canUseApp, user, sessionId, error: sessionError, logout } = useSession();
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [metadata, setMetadata] = useState<MetadataResult | null>(null);
  const [layout, setLayout] = useState<LayoutResult | null>(null);
  const [selected, setSelected] = useState<Segment | null>(null);
  const [status, setStatus] = useState<string>("");
  const [modalText, setModalText] = useState<string | null>(null);
  const [transferTarget, setTransferTarget] = useState<StoredFile | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const dragDepthRef = useRef(0);

  const activeFile = useMemo(
    () => files.find((file) => file.file_id === fileId) ?? null,
    [files, fileId],
  );

  useEffect(() => {
    if (!fileId) {
      setMetadata(null);
      setLayout(null);
      setSelected(null);
      return;
    }
    void Promise.all([getMetadata(fileId), getLayout(fileId)]).then(([meta, lay]) => {
      setMetadata(meta);
      setLayout(lay);
    });
  }, [fileId]);

  async function handleUpload(fileList: FileList | File[] | null) {
    if (!sessionId || !fileList?.length) {
      return;
    }
    setStatus("Uploading...");
    const uploaded: StoredFile[] = [];
    for (const file of Array.from(fileList)) {
      uploaded.push(await uploadFile(sessionId, file));
    }
    setFiles((current) => [...current, ...uploaded]);
    setStatus(`Uploaded ${uploaded.length} file(s).`);
    if (!fileId && uploaded[0]) {
      navigate(`/editor/${uploaded[0].file_id}`);
    }
  }

  function handleDragEnter(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepthRef.current += 1;
    setIsDragging(true);
  }

  function handleDragOver(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }

  function handleDragLeave(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepthRef.current -= 1;
    if (dragDepthRef.current <= 0) {
      dragDepthRef.current = 0;
      setIsDragging(false);
    }
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepthRef.current = 0;
    setIsDragging(false);
    void handleUpload(event.dataTransfer.files).catch((error) => setStatus(String(error)));
  }

  async function uploadSingleFile(file: File): Promise<StoredFile> {
    if (!sessionId) {
      throw new Error("Session is not ready.");
    }
    const uploaded = await uploadFile(sessionId, file);
    setFiles((current) => [...current, uploaded]);
    return uploaded;
  }

  async function runUpdatePreview() {
    if (!fileId || activeFile?.media_kind !== "video") {
      return;
    }
    setStatus("Updating embedded preview...");
    const job = await startUpdatePreviewJob(fileId, `preview_${Date.now()}.mov`);
    const finished = await pollJob(job.id);
    if (finished.status !== "succeeded" || !finished.output_file_id) {
      throw new Error(finished.error ?? "Preview update failed");
    }
    window.open(downloadUrl(finished.output_file_id), "_blank");
    setStatus("Preview update complete. Download started.");
  }

  async function runConvert(target: string) {
    if (!fileId || !activeFile) {
      return;
    }
    const extension = target.startsWith(".") ? target : `.${target}`;
    setStatus(`Converting to ${extension}...`);
    const job = await startConvertJob(fileId, `convert_${Date.now()}${extension}`, target);
    const finished = await pollJob(job.id);
    if (finished.status !== "succeeded" || !finished.output_file_id) {
      throw new Error(finished.error ?? "Conversion failed");
    }
    window.open(downloadUrl(finished.output_file_id), "_blank");
    setStatus(`Conversion complete (${extension}). Download started.`);
  }

  async function handleLogout() {
    await logout();
    setFiles([]);
    navigate("/");
  }

  return (
    <div className="app">
      <AppHeader
        title="Edit content"
        subtitle="Inspect, transfer, convert, and update metadata for video and image files."
        authReady={authReady}
        authRequired={authRequired}
        user={user}
        onLogout={() => void handleLogout()}
        showBackLink
      />

      {authReady && sessionError ? (
        <ConnectionError message={sessionError} />
      ) : authReady && !canUseApp ? (
        <section className="panel auth-panel">
          <h2>Sign in required</h2>
          <p>Sign in with your Google account to upload files and run metadata jobs.</p>
          <a className="auth-login-button" href={loginUrl("/editor")}>
            Sign in with Google
          </a>
        </section>
      ) : (
        <>
      <section className="panel">
        <h2>Library</h2>
        <div
          className={`drop-zone${isDragging ? " drop-zone-active" : ""}`}
          onDragEnter={handleDragEnter}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              fileInputRef.current?.click();
            }
          }}
          role="button"
          tabIndex={0}
          aria-label="Add files by drag and drop or click to browse"
        >
          <p className="drop-zone-title">{isDragging ? "Drop files here" : "Drag and drop files here"}</p>
          <p className="drop-zone-hint">or click to browse</p>
          <p className="drop-zone-formats">MOV, MP4, M4V, HEIC, HEIF, JPG, PNG</p>
        </div>
        <input
          ref={fileInputRef}
          className="file-input-hidden"
          type="file"
          multiple
          accept=".mov,.mp4,.m4v,.heic,.heif,.jpg,.jpeg,.png"
          onChange={(event) => {
            void handleUpload(event.target.files).catch((error) => setStatus(String(error)));
            event.target.value = "";
          }}
        />
        <ul className="file-list">
          {files.map((file) => {
            const isActive = file.file_id === fileId;
            return (
              <li key={file.file_id} className={`file-list-item${isActive ? " file-list-item-active" : ""}`}>
                <div className="file-list-row">
                  <button
                    className={`file-list-button${isActive ? " file-list-button-active" : ""}`}
                    aria-current={isActive ? "true" : undefined}
                    onClick={() => navigate(`/editor/${file.file_id}`)}
                  >
                    {file.filename} ({file.media_kind})
                  </button>
                  <button
                    type="button"
                    className="file-row-action"
                    onClick={() => setTransferTarget(file)}
                  >
                    Transfer Metadata
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      {fileId && (
        <section className="editor-grid">
          <div className="panel">
            <h2>Preview</h2>
            {/* use-credentials so the session cookie is sent when the API is
                on a different domain than the frontend; the endpoint checks
                session ownership and would otherwise 403. */}
            <img
              className="preview-image"
              src={previewUrl(fileId)}
              alt="Preview"
              crossOrigin="use-credentials"
            />
          </div>

          <div className="panel">
            <h2>Metadata</h2>
            <pre className="metadata">{metadata?.text ?? "Loading..."}</pre>
          </div>

          <div className="panel panel-memory-layout">
            <h2>Memory Layout</h2>
            <MemoryLayoutPanel
              fileId={fileId ?? null}
              layout={layout}
              selected={selected}
              onSelect={setSelected}
            />
          </div>
        </section>
      )}

      {fileId && (
        <section className="panel controls">
          <h2>Controls</h2>
          <div className="control-row">
            {activeFile?.media_kind === "video" && (
              <button onClick={() => void runUpdatePreview().catch((error) => setStatus(String(error)))}>
                Update Preview
              </button>
            )}
            {(activeFile?.media_kind === "video" ? VIDEO_CONVERT_TARGETS : activeFile?.media_kind === "image" ? IMAGE_CONVERT_TARGETS : []).map(
              (target) => (
                <button key={target} onClick={() => void runConvert(target).catch((error) => setStatus(String(error)))}>
                  Convert to {target.toUpperCase()}
                </button>
              ),
            )}
            <button onClick={() => void getUnknownHeaders(fileId).then(setModalText)}>Unknown Headers</button>
            <button onClick={() => void getUnknownMemory(fileId).then(setModalText)}>Unknown Memory</button>
          </div>
        </section>
      )}

      {status && <footer className="status">{status}</footer>}

      {transferTarget && (
        <TransferMetadataModal
          targetFile={transferTarget}
          libraryFiles={files}
          onClose={() => setTransferTarget(null)}
          onUploadSource={uploadSingleFile}
          onStatus={setStatus}
        />
      )}

      {modalText !== null && (
        <div className="modal-backdrop" onClick={() => setModalText(null)}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <pre>{modalText}</pre>
            <button onClick={() => setModalText(null)}>Close</button>
          </div>
        </div>
      )}
        </>
      )}
    </div>
  );
}
