import { useRef, useState } from "react";
import type { StoredFile } from "./api/client";
import FilePreview from "./FilePreview";

export const ACCEPTED_EXTENSIONS = ".mov,.mp4,.m4v,.heic,.heif,.jpg,.jpeg,.png";

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

type DropSlotProps = {
  label: string;
  hint: string;
  file: StoredFile | null;
  uploading: boolean;
  error: string | null;
  disabled?: boolean;
  onFile: (file: File) => void;
  onClear: () => void;
};

export default function DropSlot({
  label,
  hint,
  file,
  uploading,
  error,
  disabled = false,
  onFile,
  onClear,
}: DropSlotProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragDepth = useRef(0);

  function openPicker() {
    if (!disabled && !uploading) {
      inputRef.current?.click();
    }
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current = 0;
    setIsDragging(false);
    if (disabled || uploading) return;
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) onFile(dropped);
  }

  const stateClass = [
    "slot",
    isDragging ? "slot-dragging" : "",
    file ? "slot-filled" : "",
    error ? "slot-error" : "",
    disabled ? "slot-disabled" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="slot-wrapper">
      <div className="slot-label">{label}</div>
      <div
        className={stateClass}
        onDragEnter={(event) => {
          event.preventDefault();
          dragDepth.current += 1;
          if (!disabled && !uploading) setIsDragging(true);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          dragDepth.current -= 1;
          if (dragDepth.current <= 0) {
            dragDepth.current = 0;
            setIsDragging(false);
          }
        }}
        onDrop={handleDrop}
        onClick={openPicker}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openPicker();
          }
        }}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label={`${label}: drag and drop a file or click to browse`}
        aria-disabled={disabled}
      >
        {uploading ? (
          <p className="slot-state">Uploading…</p>
        ) : file ? (
          <>
            <FilePreview fileId={file.file_id} alt={`${label} preview`} />
            <p className="slot-filename" title={file.filename}>
              {file.filename}
            </p>
            <p className="slot-meta">
              {file.media_kind} · {formatBytes(file.size)}
            </p>
            <button
              type="button"
              className="slot-clear"
              onClick={(event) => {
                event.stopPropagation();
                onClear();
              }}
            >
              Replace
            </button>
          </>
        ) : (
          <>
            <p className="slot-state">{isDragging ? "Drop here" : hint}</p>
            <p className="slot-browse">or click to browse</p>
          </>
        )}
      </div>
      {error && <p className="slot-error-text">{error}</p>}
      <input
        ref={inputRef}
        className="file-input-hidden"
        type="file"
        accept={ACCEPTED_EXTENSIONS}
        onChange={(event) => {
          const picked = event.target.files?.[0];
          if (picked) onFile(picked);
          event.target.value = "";
        }}
      />
    </div>
  );
}
