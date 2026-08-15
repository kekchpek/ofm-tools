import { useEffect, useState } from "react";
import { getSegmentBytes, type Segment } from "./api/client";

const CATEGORY_COLORS: Record<string, string> = {
  header: "#4a90d9",
  metadata: "#43a047",
  payload: "#e53935",
  structure: "#8e24aa",
  padding: "#757575",
  unknown: "#fb8c00",
};

const CATEGORY_LABELS: Record<string, string> = {
  header: "Header",
  metadata: "Metadata",
  payload: "Payload",
  structure: "Structure",
  padding: "Padding",
  unknown: "Unknown",
};

const EDIT_SAFETY_COLORS: Record<string, string> = {
  safe: "#43a047",
  caution: "#ffa726",
  unsafe: "#e53935",
};

function formatBytes(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  if (size < 1024 * 1024 * 1024) {
    return `${(size / (1024 * 1024)).toFixed(2)} MB`;
  }
  return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

type SegmentBytes = { hex: string; text: string };

type SegmentDetailPanelProps = {
  fileId: string;
  segment: Segment;
};

export default function SegmentDetailPanel({ fileId, segment }: SegmentDetailPanelProps) {
  const [bytes, setBytes] = useState<SegmentBytes | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setBytes(null);
    setError(null);
    setLoading(true);

    getSegmentBytes(fileId, segment.offset)
      .then((result) => {
        if (!cancelled) {
          setBytes(result);
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : String(cause));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [fileId, segment.offset]);

  const categoryColor = CATEGORY_COLORS[segment.category] ?? "#777777";
  const safetyColor = EDIT_SAFETY_COLORS[segment.edit_safety.level] ?? "#999999";

  return (
    <div className="segment-detail">
      <div className="segment-detail-header">
        <h3 className="segment-detail-title">{segment.label}</h3>
        <div className="segment-detail-badges">
          <span className="segment-detail-badge" style={{ borderColor: categoryColor, color: categoryColor }}>
            {CATEGORY_LABELS[segment.category] ?? segment.category}
          </span>
          <span className="segment-detail-badge" style={{ borderColor: safetyColor, color: safetyColor }}>
            {segment.edit_safety.mark} {segment.edit_safety.label}
          </span>
        </div>
      </div>

      <dl className="segment-detail-meta">
        <div className="segment-detail-meta-row">
          <dt>Offset</dt>
          <dd>
            0x{segment.offset.toString(16)} ({segment.offset})
          </dd>
        </div>
        <div className="segment-detail-meta-row">
          <dt>Size</dt>
          <dd>
            {formatBytes(segment.size)} ({segment.size} bytes)
          </dd>
        </div>
        <div className="segment-detail-meta-row">
          <dt>End</dt>
          <dd>
            0x{segment.end.toString(16)} ({segment.end})
          </dd>
        </div>
        <div className="segment-detail-meta-row">
          <dt>Path</dt>
          <dd>{segment.path_label || segment.path.join(" / ") || "—"}</dd>
        </div>
      </dl>

      <section className="segment-detail-section">
        <h4 className="segment-detail-section-title">Edit safety</h4>
        <p className="segment-detail-description">{segment.edit_safety.reason}</p>
      </section>

      <section className="segment-detail-section">
        <h4 className="segment-detail-section-title">Bytes</h4>
        <p className="segment-detail-section-hint">First 512 bytes of the segment.</p>
        {loading && <p className="segment-detail-section-hint">Loading bytes…</p>}
        {error && <p className="segment-detail-section-hint">Could not load bytes: {error}</p>}
        {bytes && (
          <>
            <pre className="segment-detail-code">{bytes.hex}</pre>
            <h4 className="segment-detail-section-title">Text</h4>
            <pre className="segment-detail-code">{bytes.text}</pre>
          </>
        )}
      </section>
    </div>
  );
}
