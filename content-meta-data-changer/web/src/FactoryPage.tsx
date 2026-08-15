import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  downloadUrl,
  loginUrl,
  pollJob,
  startFactoryJob,
  uploadFile,
  type StoredFile,
} from "./api/client";
import AppHeader from "./AppHeader";
import ConnectionError from "./ConnectionError";
import DropSlot from "./DropSlot";
import FilePreview from "./FilePreview";
import { useSession } from "./useSession";

type Slot = {
  file: StoredFile | null;
  uploading: boolean;
  error: string | null;
};

type PieceStatus = "idle" | "generating" | "done" | "error";

type ContentPiece = {
  id: string;
  name: string;
  /** Result file name without extension; empty means "use the suggested name". */
  outputStem: string;
  source: Slot;
  metadata: Slot;
  status: PieceStatus;
  resultFileId: string | null;
  resultName: string | null;
  error: string | null;
};

const EMPTY_SLOT: Slot = { file: null, uploading: false, error: null };

let pieceCounter = 0;

function newPiece(position: number): ContentPiece {
  pieceCounter += 1;
  return {
    id: `piece-${pieceCounter}-${Date.now()}`,
    name: `Content piece ${position}`,
    outputStem: "",
    source: { ...EMPTY_SLOT },
    metadata: { ...EMPTY_SLOT },
    status: "idle",
    resultFileId: null,
    resultName: null,
    error: null,
  };
}

function extensionOf(file: StoredFile | null): string {
  return file?.filename.match(/\.[^.]+$/)?.[0].toLowerCase() ?? "";
}

/** Name used when the user leaves the result field blank. */
function suggestedStem(source: StoredFile | null): string {
  if (!source) return "";
  return `${source.filename.replace(/\.[^.]+$/, "")}_ofm`;
}

export default function FactoryPage() {
  const navigate = useNavigate();
  const { authReady, authRequired, canUseApp, user, sessionId, error: sessionError, logout } = useSession();
  const [pieces, setPieces] = useState<ContentPiece[]>([newPiece(1)]);

  const updatePiece = useCallback((id: string, patch: (piece: ContentPiece) => ContentPiece) => {
    setPieces((current) => current.map((piece) => (piece.id === id ? patch(piece) : piece)));
  }, []);

  async function handleLogout() {
    await logout();
    navigate("/");
  }

  async function handleFile(pieceId: string, which: "source" | "metadata", file: File) {
    if (!sessionId) {
      updatePiece(pieceId, (piece) => ({
        ...piece,
        [which]: { ...piece[which], error: "Session is not ready yet. Try again in a moment." },
      }));
      return;
    }

    // A new input invalidates any result already generated from the old one.
    updatePiece(pieceId, (piece) => ({
      ...piece,
      [which]: { file: null, uploading: true, error: null },
      status: "idle",
      resultFileId: null,
      resultName: null,
      error: null,
    }));

    try {
      const uploaded = await uploadFile(sessionId, file);
      updatePiece(pieceId, (piece) => ({
        ...piece,
        [which]: { file: uploaded, uploading: false, error: null },
      }));
    } catch (error) {
      updatePiece(pieceId, (piece) => ({
        ...piece,
        [which]: { file: null, uploading: false, error: String(error) },
      }));
    }
  }

  function clearSlot(pieceId: string, which: "source" | "metadata") {
    updatePiece(pieceId, (piece) => ({
      ...piece,
      [which]: { ...EMPTY_SLOT },
      status: "idle",
      resultFileId: null,
      resultName: null,
      error: null,
    }));
  }

  async function generate(piece: ContentPiece) {
    const source = piece.source.file;
    const metadata = piece.metadata.file;
    if (!source || !metadata) return;

    updatePiece(piece.id, (current) => ({ ...current, status: "generating", error: null }));

    const stem = piece.outputStem.trim() || suggestedStem(source);
    const filename = `${stem}${extensionOf(metadata)}`;

    try {
      const job = await startFactoryJob(source.file_id, metadata.file_id, filename);
      const finished = await pollJob(job.id);
      if (finished.status !== "succeeded" || !finished.output_file_id) {
        throw new Error(finished.error ?? "Generation failed");
      }
      updatePiece(piece.id, (current) => ({
        ...current,
        status: "done",
        resultFileId: finished.output_file_id,
        resultName: filename,
        error: null,
      }));
    } catch (error) {
      updatePiece(piece.id, (current) => ({
        ...current,
        status: "error",
        error: String(error instanceof Error ? error.message : error),
      }));
    }
  }

  function addPiece() {
    setPieces((current) => [...current, newPiece(current.length + 1)]);
  }

  function removePiece(id: string) {
    setPieces((current) => {
      const next = current.filter((piece) => piece.id !== id);
      return next.length ? next : [newPiece(1)];
    });
  }

  function renamePiece(id: string, name: string) {
    updatePiece(id, (piece) => ({ ...piece, name }));
  }

  return (
    <div className="app">
      <AppHeader
        title="OFM Factory"
        subtitle="Rebuild your content in a donor file's format, wearing its metadata."
        authReady={authReady}
        authRequired={authRequired}
        user={user}
        onLogout={() => void handleLogout()}
        showBackLink
      />

      {!authReady ? (
        <section className="panel">
          <p>Loading…</p>
        </section>
      ) : sessionError ? (
        <ConnectionError message={sessionError} />
      ) : !canUseApp ? (
        <section className="panel auth-panel">
          <h2>Sign in required</h2>
          <p>Sign in with your Google account to upload files and generate results.</p>
          <a className="auth-login-button" href={loginUrl("/factory")}>
            Sign in with Google
          </a>
        </section>
      ) : (
        <>
          <section className="panel factory-intro">
            <p>
              Each content piece takes the picture or footage from <strong>Source content</strong> and
              rebuilds it in the format of <strong>Metadata content</strong>, carrying that file's
              metadata. Both files must be the same media type — two photos, or two videos.
            </p>
          </section>

          <div className="piece-list">
            {pieces.map((piece, index) => {
              const source = piece.source.file;
              const metadata = piece.metadata.file;
              const mismatch =
                source !== null &&
                metadata !== null &&
                source.media_kind !== metadata.media_kind;
              const busy = piece.status === "generating";
              const canGenerate = source !== null && metadata !== null && !mismatch && !busy;

              return (
                <section className="panel piece" key={piece.id}>
                  <div className="piece-header">
                    <input
                      className="piece-name"
                      value={piece.name}
                      onChange={(event) => renamePiece(piece.id, event.target.value)}
                      placeholder={`Content piece ${index + 1}`}
                      aria-label={`Name of content piece ${index + 1}`}
                      spellCheck={false}
                    />
                    <button
                      type="button"
                      className="piece-remove"
                      onClick={() => removePiece(piece.id)}
                      disabled={busy}
                    >
                      Remove
                    </button>
                  </div>

                  <div className="piece-grid">
                    <DropSlot
                      label="1 · Source content"
                      hint="Drop the file whose picture or footage you want to keep"
                      file={piece.source.file}
                      uploading={piece.source.uploading}
                      error={piece.source.error}
                      disabled={busy}
                      onFile={(file) => void handleFile(piece.id, "source", file)}
                      onClear={() => clearSlot(piece.id, "source")}
                    />

                    <DropSlot
                      label="2 · Metadata content"
                      hint="Drop the file whose format and metadata you want to copy"
                      file={piece.metadata.file}
                      uploading={piece.metadata.uploading}
                      error={piece.metadata.error}
                      disabled={busy}
                      onFile={(file) => void handleFile(piece.id, "metadata", file)}
                      onClear={() => clearSlot(piece.id, "metadata")}
                    />

                    <div className="slot-wrapper">
                      <div className="slot-label">3 · Result</div>
                      <div className={`slot slot-result${piece.status === "done" ? " slot-filled" : ""}`}>
                        {piece.status === "done" && piece.resultFileId ? (
                          <>
                            <FilePreview fileId={piece.resultFileId} alt="Result preview" />
                            <p className="slot-filename" title={piece.resultName ?? ""}>
                              {piece.resultName}
                            </p>
                            <p className="slot-meta">Ready</p>
                            <a
                              className="slot-download"
                              href={downloadUrl(piece.resultFileId)}
                              download={piece.resultName ?? undefined}
                            >
                              Download
                            </a>
                          </>
                        ) : busy ? (
                          <p className="slot-state">Generating…</p>
                        ) : (
                          <p className="slot-state slot-state-muted">
                            Result appears here once generated
                          </p>
                        )}
                      </div>

                      <label className="output-name">
                        <span className="output-name-label">Result file name</span>
                        <span className="output-name-row">
                          <input
                            className="output-name-input"
                            value={piece.outputStem}
                            placeholder={suggestedStem(source) || "file name"}
                            onChange={(event) =>
                              updatePiece(piece.id, (current) => ({
                                ...current,
                                outputStem: event.target.value,
                              }))
                            }
                            disabled={busy}
                            spellCheck={false}
                          />
                          <span className="output-name-ext">{extensionOf(metadata) || "…"}</span>
                        </span>
                      </label>
                    </div>
                  </div>

                  {mismatch && (
                    <p className="piece-warning">
                      Source content is {source?.media_kind} and metadata content is{" "}
                      {metadata?.media_kind}. Both must be the same media type.
                    </p>
                  )}
                  {piece.status === "error" && piece.error && (
                    <p className="piece-error">{piece.error}</p>
                  )}

                  <div className="piece-actions">
                    <button
                      type="button"
                      className="generate-button"
                      onClick={() => void generate(piece)}
                      disabled={!canGenerate}
                    >
                      {busy ? "Generating…" : piece.status === "done" ? "Regenerate" : "Generate Result"}
                    </button>
                  </div>
                </section>
              );
            })}
          </div>

          <div className="piece-list-actions">
            <button type="button" className="add-piece-button" onClick={addPiece}>
              + Add content piece
            </button>
          </div>
        </>
      )}
    </div>
  );
}
