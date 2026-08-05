import { useMemo, useRef, useState } from "react";
import { downloadUrl, pollJob, startTransferJob, type StoredFile } from "./api/client";

const SUPPORTED_FORMATS = ".heic, .heif, .jpg, .jpeg, .m4v, .mov, .mp4, .png";

type TransferMetadataModalProps = {
  targetFile: StoredFile;
  libraryFiles: StoredFile[];
  onClose: () => void;
  onUploadSource: (file: File) => Promise<StoredFile>;
  onStatus: (message: string) => void;
};

function defaultOutputFilename(filename: string): string {
  const dot = filename.lastIndexOf(".");
  if (dot <= 0) {
    return `${filename}_with_metadata.mp4`;
  }
  const stem = filename.slice(0, dot);
  const suffix = filename.slice(dot);
  return `${stem}_with_metadata${suffix}`;
}

function basename(pathOrName: string): string {
  const normalized = pathOrName.replace(/\\/g, "/");
  const parts = normalized.split("/");
  return parts[parts.length - 1] || pathOrName;
}

export default function TransferMetadataModal({
  targetFile,
  libraryFiles,
  onClose,
  onUploadSource,
  onStatus,
}: TransferMetadataModalProps) {
  const sourceOptions = useMemo(
    () => libraryFiles.filter((file) => file.file_id !== targetFile.file_id),
    [libraryFiles, targetFile.file_id],
  );

  const [sourceFileId, setSourceFileId] = useState(sourceOptions[0]?.file_id ?? "");
  const [outputFilename, setOutputFilename] = useState(defaultOutputFilename(targetFile.filename));
  const [busy, setBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState(`Supported formats: ${SUPPORTED_FORMATS}`);
  const sourceInputRef = useRef<HTMLInputElement | null>(null);

  async function handleBrowseSource(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    try {
      setBusy(true);
      setStatusMessage("Uploading metadata source...");
      const uploaded = await onUploadSource(file);
      setSourceFileId(uploaded.file_id);
      setStatusMessage(`Added ${uploaded.filename} as metadata source.`);
    } catch (error) {
      setStatusMessage(String(error));
    } finally {
      setBusy(false);
    }
  }

  async function handleBrowseOutput() {
    const suggested = outputFilename || defaultOutputFilename(targetFile.filename);
    if (window.showSaveFilePicker) {
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName: suggested,
        });
        setOutputFilename(handle.name);
        return;
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
      }
    }
    const entered = window.prompt("Save result as:", suggested);
    if (entered?.trim()) {
      setOutputFilename(basename(entered.trim()));
    }
  }

  async function handleTransfer() {
    if (!sourceFileId) {
      window.alert("Choose a file to copy metadata from.");
      return;
    }
    if (sourceFileId === targetFile.file_id) {
      window.alert("Metadata source must be a different file from the target video.");
      return;
    }

    const outputName = outputFilename.trim();
    if (!outputName) {
      window.alert("Choose where to save the result file.");
      return;
    }

    const outputBasename = basename(outputName);
    const sourceFile = libraryFiles.find((file) => file.file_id === sourceFileId);
    if (
      outputBasename === targetFile.filename ||
      (sourceFile && outputBasename === sourceFile.filename)
    ) {
      window.alert("The output file must be different from both the target and metadata source files.");
      return;
    }

    if (busy) {
      window.alert("Please wait for the current transfer to finish.");
      return;
    }

    try {
      setBusy(true);
      setStatusMessage("Transferring metadata…");
      onStatus("Running metadata transfer...");
      const job = await startTransferJob(targetFile.file_id, sourceFileId, outputBasename);
      const finished = await pollJob(job.id);
      if (finished.status !== "succeeded" || !finished.output_file_id) {
        throw new Error(finished.error ?? "Transfer failed");
      }
      window.open(downloadUrl(finished.output_file_id), "_blank");
      const message = `Saved to ${outputBasename}`;
      setStatusMessage(message);
      onStatus("Transfer complete. Download started.");
      window.alert(`Metadata copied successfully.\n\nSaved to:\n${outputBasename}`);
    } catch (error) {
      const message = String(error);
      setStatusMessage("Metadata transfer failed");
      onStatus(message);
      window.alert(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal transfer-modal"
        role="dialog"
        aria-labelledby="transfer-modal-title"
        aria-modal="true"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="transfer-modal-title" className="transfer-modal-title">
          Transfer Metadata
        </h2>

        <p className="transfer-modal-intro">
          Create a new file that keeps the media from the target file and copies metadata from another
          file. Videos use QuickTime atom grafting; images use EXIF/PNG metadata.
        </p>

        <div className="transfer-form">
          <div className="transfer-form-row">
            <label className="transfer-form-label" htmlFor="transfer-target">
              Keep video from:
            </label>
            <div id="transfer-target" className="transfer-form-value transfer-form-path">
              {targetFile.filename}
            </div>
          </div>

          <div className="transfer-form-row">
            <label className="transfer-form-label" htmlFor="transfer-source">
              Copy metadata from:
            </label>
            <div className="transfer-input-row">
              <select
                id="transfer-source"
                value={sourceFileId}
                disabled={busy}
                onChange={(event) => setSourceFileId(event.target.value)}
              >
                {sourceOptions.length === 0 ? (
                  <option value="">(choose a file)</option>
                ) : null}
                {sourceOptions.map((file) => (
                  <option key={file.file_id} value={file.file_id}>
                    {file.filename}
                  </option>
                ))}
              </select>
              <button type="button" disabled={busy} onClick={() => sourceInputRef.current?.click()}>
                Browse…
              </button>
              <input
                ref={sourceInputRef}
                className="file-input-hidden"
                type="file"
                accept=".mov,.mp4,.m4v,.heic,.heif,.jpg,.jpeg,.png"
                onChange={(event) => void handleBrowseSource(event)}
              />
            </div>
          </div>

          <div className="transfer-form-row">
            <label className="transfer-form-label" htmlFor="transfer-output">
              Save result to:
            </label>
            <div className="transfer-input-row">
              <input
                id="transfer-output"
                type="text"
                value={outputFilename}
                disabled={busy}
                placeholder="Choose where to save the new file"
                onChange={(event) => setOutputFilename(event.target.value)}
              />
              <button type="button" disabled={busy} onClick={() => void handleBrowseOutput()}>
                Browse…
              </button>
            </div>
          </div>
        </div>

        <div className="transfer-modal-actions">
          <button type="button" disabled={busy} onClick={() => void handleTransfer()}>
            Transfer Metadata
          </button>
          <button type="button" disabled={busy} onClick={onClose}>
            Close
          </button>
        </div>

        <footer className="transfer-modal-status">{statusMessage}</footer>
      </div>
    </div>
  );
}
