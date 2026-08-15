import { useEffect, useRef } from "react";
import type { LayoutResult, Segment } from "./api/client";

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

type SegmentListPanelProps = {
  layout: LayoutResult | null;
  selected: Segment | null;
  onSelect: (segment: Segment | null) => void;
  isActive: boolean;
};

export default function SegmentListPanel({ layout, selected, onSelect, isActive }: SegmentListPanelProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const segments = layout?.segments ?? [];
  const selectedIndex = selected
    ? segments.findIndex((segment) => segment.offset === selected.offset)
    : -1;

  useEffect(() => {
    if (!isActive || selectedIndex < 0) {
      return;
    }
    const list = listRef.current;
    const item = list?.querySelector<HTMLElement>(`[data-index="${selectedIndex}"]`);
    item?.scrollIntoView({ block: "nearest" });
  }, [isActive, selectedIndex]);

  function moveSelection(delta: number) {
    if (segments.length === 0) {
      return;
    }
    const base = selectedIndex < 0 ? (delta > 0 ? -1 : segments.length) : selectedIndex;
    const next = Math.max(0, Math.min(segments.length - 1, base + delta));
    onSelect(segments[next] ?? null);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        moveSelection(1);
        break;
      case "ArrowUp":
        event.preventDefault();
        moveSelection(-1);
        break;
      case "PageDown":
        event.preventDefault();
        moveSelection(10);
        break;
      case "PageUp":
        event.preventDefault();
        moveSelection(-10);
        break;
      case "Home":
        event.preventDefault();
        onSelect(segments[0] ?? null);
        break;
      case "End":
        event.preventDefault();
        onSelect(segments[segments.length - 1] ?? null);
        break;
      default:
        break;
    }
  }

  if (!layout) {
    return (
      <div className="segment-list-panel">
        <p className="segment-list-empty">Load a file to see its segments.</p>
      </div>
    );
  }

  if (segments.length === 0) {
    return (
      <div className="segment-list-panel">
        <p className="segment-list-empty">No segments were detected in this file.</p>
      </div>
    );
  }

  return (
    <div className="segment-list-panel">
      <div
        ref={listRef}
        className="segment-list"
        role="listbox"
        aria-label="File segments"
        tabIndex={0}
        onKeyDown={handleKeyDown}
      >
        {segments.map((segment, index) => {
          const isSelected = index === selectedIndex;
          return (
            <button
              key={`${segment.offset}-${index}`}
              type="button"
              role="option"
              aria-selected={isSelected}
              data-index={index}
              className={`segment-list-item${isSelected ? " segment-list-item-selected" : ""}`}
              onClick={() => onSelect(segment)}
            >
              <span className="segment-list-number">{index + 1}</span>
              <span
                className="memory-layout-mark"
                style={{ color: EDIT_SAFETY_COLORS[segment.edit_safety.level] }}
                title={`${segment.edit_safety.label}: ${segment.edit_safety.reason}`}
              >
                {segment.edit_safety.mark}
              </span>
              <span className="segment-list-label" title={segment.path_label || segment.label}>
                {segment.label}
              </span>
              <span className="segment-list-meta">
                0x{segment.offset.toString(16)} · {formatBytes(segment.size)}
              </span>
              <span className="segment-list-category">
                {CATEGORY_LABELS[segment.category] ?? segment.category}
              </span>
            </button>
          );
        })}
      </div>
      <p className="segment-list-hint">
        Click a segment to inspect it. Focus the list and use arrow keys to move through segments.
      </p>
    </div>
  );
}
