import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  createPiece,
  deletePiece,
  downloadUrl,
  getOfm,
  getStorageUsage,
  listPieces,
  loginUrl,
  pollJob,
  startFactoryJob,
  updatePiece,
  uploadFile,
  type ContentPiece,
  type Ofm,
  type PiecePatch,
  type StorageUsage,
  type StoredFile,
} from "./api/client";
import AppHeader from "./AppHeader";
import ConnectionError from "./ConnectionError";
import DropSlot from "./DropSlot";
import MembersPanel from "./MembersPanel";
import FilePreview from "./FilePreview";
import { useSession } from "./useSession";

type Slot = {
  file: StoredFile | null;
  uploading: boolean;
  error: string | null;
};

type PieceStatus = "idle" | "generating" | "error";

type Piece = {
  id: string;
  name: string;
  outputStem: string;
  source: Slot;
  metadata: Slot;
  result: StoredFile | null;
  resultName: string | null;
  status: PieceStatus;
  error: string | null;
};

const EMPTY_SLOT: Slot = { file: null, uploading: false, error: null };
const SAVE_DEBOUNCE_MS = 700;

function slotFrom(file: StoredFile | null): Slot {
  return { file, uploading: false, error: null };
}

function fromDTO(dto: ContentPiece): Piece {
  return {
    id: dto.id,
    name: dto.name,
    outputStem: dto.output_stem,
    source: slotFrom(dto.source_file),
    metadata: slotFrom(dto.metadata_file),
    result: dto.result_file,
    resultName: dto.result_filename,
    status: "idle",
    error: null,
  };
}

function extensionOf(file: StoredFile | null): string {
  return file?.filename.match(/\.[^.]+$/)?.[0].toLowerCase() ?? "";
}

function suggestedStem(source: StoredFile | null): string {
  if (!source) return "";
  return `${source.filename.replace(/\.[^.]+$/, "")}_ofm`;
}

function alreadyHasExtension(name: string, extension: string): boolean {
  return extension !== "" && name.toLowerCase().endsWith(extension);
}

/**
 * Give the name exactly one trailing extension — the donor's. Must match
 * `normalize_output_name` on the server, which has the final say.
 */
function withExtension(name: string, extension: string): string {
  if (!extension || alreadyHasExtension(name, extension)) {
    return name;
  }
  return `${name.replace(/\.[^.]+$/, "")}${extension}`;
}

function formatBytes(size: number): string {
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(0)} MB`;
  return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export default function FactoryPage() {
  const navigate = useNavigate();
  const { ofmId } = useParams();
  const { authReady, authRequired, canUseApp, user, sessionId, error: sessionError, logout } =
    useSession();

  const [ofm, setOfm] = useState<Ofm | null>(null);
  const [pieces, setPieces] = useState<Piece[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [storage, setStorage] = useState<StorageUsage | null>(null);
  const [saving, setSaving] = useState(0);
  const [adding, setAdding] = useState(false);

  const saveTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const patch = useCallback((id: string, update: (piece: Piece) => Piece) => {
    setPieces((current) => current.map((piece) => (piece.id === id ? update(piece) : piece)));
  }, []);

  const refreshStorage = useCallback(() => {
    void getStorageUsage().then(setStorage).catch(() => undefined);
  }, []);

  /** Persist immediately; used for structural changes like files and results. */
  const save = useCallback(
    async (id: string, body: PiecePatch) => {
      setSaving((count) => count + 1);
      try {
        await updatePiece(id, body);
      } catch (cause) {
        patch(id, (piece) => ({ ...piece, error: String(cause) }));
      } finally {
        setSaving((count) => count - 1);
      }
    },
    [patch],
  );

  /** Persist after typing settles, so every keystroke is not a request. */
  const saveDebounced = useCallback(
    (id: string, body: PiecePatch) => {
      clearTimeout(saveTimers.current[id]);
      saveTimers.current[id] = setTimeout(() => void save(id, body), SAVE_DEBOUNCE_MS);
    },
    [save],
  );

  // Flush pending edits if the component goes away mid-typing.
  useEffect(() => {
    const timers = saveTimers.current;
    return () => Object.values(timers).forEach(clearTimeout);
  }, []);

  useEffect(() => {
    if (!sessionId || loaded || !ofmId) {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        // Read-only on purpose. Creating a starter piece here would run twice
        // under StrictMode's double mount — both passes see an empty list
        // before either write lands, and two pieces appear.
        const [details, existing] = await Promise.all([getOfm(ofmId), listPieces(ofmId)]);
        if (cancelled) return;
        setOfm(details);
        setPieces(existing.map(fromDTO));
        setLoadError(null);
      } catch (cause) {
        if (!cancelled) setLoadError(String(cause));
      } finally {
        if (!cancelled) {
          setLoaded(true);
          refreshStorage();
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, loaded, ofmId, refreshStorage]);

  async function handleLogout() {
    await logout();
    navigate("/");
  }

  async function handleFile(pieceId: string, which: "source" | "metadata", file: File) {
    if (!sessionId) return;

    // A new input invalidates any result generated from the old one.
    patch(pieceId, (piece) => ({
      ...piece,
      [which]: { file: null, uploading: true, error: null },
      result: null,
      resultName: null,
      status: "idle",
      error: null,
    }));

    try {
      const uploaded = await uploadFile(sessionId, file);
      patch(pieceId, (piece) => ({ ...piece, [which]: slotFrom(uploaded) }));
      await save(pieceId, {
        [which === "source" ? "source_file_id" : "metadata_file_id"]: uploaded.file_id,
        clear: ["result_file_id", "result_filename"],
      });
      refreshStorage();
    } catch (cause) {
      const message = String(cause);
      patch(pieceId, (piece) => ({
        ...piece,
        [which]: { file: null, uploading: false, error: message },
      }));
    }
  }

  async function clearSlot(pieceId: string, which: "source" | "metadata") {
    patch(pieceId, (piece) => ({
      ...piece,
      [which]: { ...EMPTY_SLOT },
      result: null,
      resultName: null,
      status: "idle",
      error: null,
    }));
    await save(pieceId, {
      clear: [
        which === "source" ? "source_file_id" : "metadata_file_id",
        "result_file_id",
        "result_filename",
      ],
    });
    refreshStorage();
  }

  async function generate(piece: Piece) {
    const source = piece.source.file;
    const metadata = piece.metadata.file;
    if (!source || !metadata) return;

    patch(piece.id, (current) => ({ ...current, status: "generating", error: null }));

    const stem = piece.outputStem.trim() || suggestedStem(source);
    const filename = withExtension(stem, extensionOf(metadata));

    try {
      const job = await startFactoryJob(source.file_id, metadata.file_id, filename, sessionId ?? undefined);
      const finished = await pollJob(job.id);
      if (finished.status !== "succeeded" || !finished.output_file_id) {
        throw new Error(finished.error ?? "Generation failed");
      }
      const resultId = finished.output_file_id;
      patch(piece.id, (current) => ({
        ...current,
        status: "idle",
        result: {
          file_id: resultId,
          session_id: sessionId ?? source.session_id,
          filename,
          size: 0,
          media_kind: source.media_kind,
        },
        resultName: filename,
        error: null,
      }));
      await save(piece.id, { result_file_id: resultId, result_filename: filename });
      refreshStorage();
    } catch (cause) {
      patch(piece.id, (current) => ({
        ...current,
        status: "error",
        error: cause instanceof Error ? cause.message : String(cause),
      }));
    }
  }

  async function addPiece() {
    if (adding) {
      return; // an impatient double-click must not create two
    }
    setAdding(true);
    try {
      const created = await createPiece(ofmId!, `Content piece ${pieces.length + 1}`);
      setPieces((current) => [...current, fromDTO(created)]);
      setLoadError(null);
    } catch (cause) {
      setLoadError(String(cause));
    } finally {
      setAdding(false);
    }
  }

  async function removePiece(id: string) {
    clearTimeout(saveTimers.current[id]);
    setPieces((current) => current.filter((piece) => piece.id !== id));
    try {
      await deletePiece(id);
    } catch (cause) {
      setLoadError(String(cause));
    }
    refreshStorage();
  }

  const quotaPercent = storage
    ? Math.min(100, Math.round((storage.used_bytes / Math.max(1, storage.quota_bytes)) * 100))
    : 0;

  return (
    <div className="app">
      <AppHeader
        title={ofm?.name ?? "OFM Factory"}
        subtitle="Rebuild your content in a donor file's format, wearing its metadata."
        authReady={authReady}
        authRequired={authRequired}
        user={user}
        onLogout={() => void handleLogout()}
        showBackLink
        backTo="/factory"
        backLabel="All OFMs"
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
            <div className="factory-intro-row">
              <p>
                Each content piece takes the picture or footage from{" "}
                <strong>Source content</strong> and rebuilds it in the format of{" "}
                <strong>Metadata content</strong>, carrying that file's metadata. Both files must be
                the same media type. Your pieces are saved to your account automatically.
              </p>
              {storage && (
                <div className="storage-meter" title="Storage used by your saved pieces">
                  <div className="storage-meter-label">
                    {formatBytes(storage.used_bytes)} of {formatBytes(storage.quota_bytes)}
                  </div>
                  <div className="storage-meter-track">
                    <div
                      className={`storage-meter-fill${quotaPercent > 90 ? " storage-meter-full" : ""}`}
                      style={{ width: `${quotaPercent}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
            <p className="factory-save-state">
              {saving > 0 ? "Saving…" : loaded ? "All changes saved" : "Loading your pieces…"}
            </p>
          </section>

          {loadError && (
            <section className="panel">
              <p className="piece-error">{loadError}</p>
            </section>
          )}

          {ofmId && <MembersPanel ofmId={ofmId} />}

          {loaded && pieces.length === 0 && (
            <section className="panel piece-empty">
              <h2>No content pieces yet</h2>
              <p>
                A content piece pairs a source file with a metadata donor and produces one result.
                Add as many as you need — they are saved to your account.
              </p>
              <button
                type="button"
                className="generate-button"
                onClick={() => void addPiece()}
                disabled={adding}
              >
                {adding ? "Adding…" : "Add your first content piece"}
              </button>
            </section>
          )}

          <div className="piece-list">
            {pieces.map((piece, index) => {
              const source = piece.source.file;
              const metadata = piece.metadata.file;
              const mismatch =
                source !== null && metadata !== null && source.media_kind !== metadata.media_kind;
              const busy = piece.status === "generating";
              const canGenerate = source !== null && metadata !== null && !mismatch && !busy;

              return (
                <section className="panel piece" key={piece.id}>
                  <div className="piece-header">
                    <input
                      className="piece-name"
                      value={piece.name}
                      onChange={(event) => {
                        const name = event.target.value;
                        patch(piece.id, (current) => ({ ...current, name }));
                        saveDebounced(piece.id, { name });
                      }}
                      placeholder={`Content piece ${index + 1}`}
                      aria-label={`Name of content piece ${index + 1}`}
                      spellCheck={false}
                    />
                    <button
                      type="button"
                      className="piece-remove"
                      onClick={() => void removePiece(piece.id)}
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
                      onClear={() => void clearSlot(piece.id, "source")}
                    />

                    <DropSlot
                      label="2 · Metadata content"
                      hint="Drop the file whose format and metadata you want to copy"
                      file={piece.metadata.file}
                      uploading={piece.metadata.uploading}
                      error={piece.metadata.error}
                      disabled={busy}
                      onFile={(file) => void handleFile(piece.id, "metadata", file)}
                      onClear={() => void clearSlot(piece.id, "metadata")}
                    />

                    <div className="slot-wrapper">
                      <div className="slot-label">3 · Result</div>
                      <div className={`slot slot-result${piece.result ? " slot-filled" : ""}`}>
                        {piece.result ? (
                          <>
                            <FilePreview fileId={piece.result.file_id} alt="Result preview" />
                            <p className="slot-filename" title={piece.resultName ?? ""}>
                              {piece.resultName}
                            </p>
                            <p className="slot-meta">Ready</p>
                            <a
                              className="slot-download"
                              href={downloadUrl(piece.result.file_id)}
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
                            onChange={(event) => {
                              const outputStem = event.target.value;
                              patch(piece.id, (current) => ({ ...current, outputStem }));
                              saveDebounced(piece.id, { output_stem: outputStem });
                            }}
                            disabled={busy}
                            spellCheck={false}
                          />
                          {!alreadyHasExtension(piece.outputStem.trim(), extensionOf(metadata)) && (
                            <span className="output-name-ext">{extensionOf(metadata) || "…"}</span>
                          )}
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
                  {piece.error && <p className="piece-error">{piece.error}</p>}

                  <div className="piece-actions">
                    <button
                      type="button"
                      className="generate-button"
                      onClick={() => void generate(piece)}
                      disabled={!canGenerate}
                    >
                      {busy ? "Generating…" : piece.result ? "Regenerate" : "Generate Result"}
                    </button>
                  </div>
                </section>
              );
            })}
          </div>

          {pieces.length > 0 && (
            <div className="piece-list-actions">
              <button
                type="button"
                className="add-piece-button"
                onClick={() => void addPiece()}
                disabled={adding}
              >
                {adding ? "Adding…" : "+ Add content piece"}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
