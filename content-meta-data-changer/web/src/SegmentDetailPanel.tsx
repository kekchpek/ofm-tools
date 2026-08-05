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

type SegmentDetailPanelProps = {
  fileId: string;
  segment: Segment;
};

function formatBytes(size: number): string {
  if (size < 1024) {
    return `${size} bytes`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB (${size.toLocaleString()} bytes)`;
  }
  return `${(size / (1024 * 1024)).toFixed(2)} MB (${size.toLocaleString()} bytes)`;
}

export default function SegmentDetailPanel({ fileId, segment }: SegmentDetailPanelProps) {
  const [hexPreview, setHexPreview] = useState("");
  const [textPreview, setTextPreview] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setLoadError(null);
    setHexPreview("");
    setTextPreview("");

    void getSegmentBytes(fileId, segment.offset)
      .then((result) => {
        if (cancelled) {
          return;
        }
        setHexPreview(result.hex);
        setTextPreview(result.text);
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        setLoadError(String(error));
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [fileId, segment.offset]);

  const categoryLabel = CATEGORY_LABELS[segment.category] ?? segment.category;
  const categoryColor = CATEGORY_COLORS[segment.category] ?? "#777777";
  const safetyColor = EDIT_SAFETY_COLORS[segment.edit_safety.level] ?? "#ffa726";

  return (
    <article className="segment-detail">
      <header className="segment-detail-header">
        <h3 className="segment-detail-title">{segment.label}</h3>
        <div className="segment-detail-badges">
          <span
            className="segment-detail-badge segment-detail-badge-category"
            style={{ borderColor: categoryColor, color: categoryColor }}
          >
            {categoryLabel}
          </span>
          <span
            className="segment-detail-badge segment-detail-badge-safety"
            style={{ borderColor: safetyColor, color: safetyColor }}
          >
            {segment.edit_safety.mark} {segment.edit_safety.label}
          </span>
        </div>
      </header>

      <dl className="segment-detail-meta">
        <div className="segment-detail-meta-row">
          <dt>Path</dt>
          <dd>{segment.path_label}</dd>
        </div>
        <div className="segment-detail-meta-row">
          <dt>Offset</dt>
          <dd>
            0x{segment.offset.toString(16)} – 0x{segment.end.toString(16)}
          </dd>
        </div>
        <div className="segment-detail-meta-row">
          <dt>Size</dt>
          <dd>{formatBytes(segment.size)}</dd>
        </div>
      </dl>

      <section className="segment-detail-section">
        <h4 className="segment-detail-section-title">Description</h4>
        <p className="segment-detail-description">{segment.edit_safety.reason}</p>
      </section>

      <section className="segment-detail-section">
        <h4 className="segment-detail-section-title">Binary</h4>
        <p className="segment-detail-section-hint">Hex dump of the first bytes in this segment.</p>
        <pre className="segment-detail-code">
          {loadError ?? (isLoading ? "Loading..." : hexPreview || "(empty segment)")}
        </pre>
      </section>

      <section className="segment-detail-section">
        <h4 className="segment-detail-section-title">Text</h4>
        <p className="segment-detail-section-hint">Printable characters found in those bytes.</p>
        <pre className="segment-detail-code">
          {loadError ? "—" : isLoading ? "Loading..." : textPreview || "(no printable text)"}
        </pre>
      </section>
    </article>
  );
}
