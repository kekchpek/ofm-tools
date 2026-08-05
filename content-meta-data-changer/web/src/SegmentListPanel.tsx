import { useEffect, useMemo, useRef } from "react";
import type { LayoutResult, Segment } from "./api/client";

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
  isActive?: boolean;
};

export default function SegmentListPanel({ layout, selected, onSelect, isActive = false }: SegmentListPanelProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const selectedOffsetRef = useRef<number | null>(null);

  const numberWidth = useMemo(() => {
    const total = layout?.segments.length ?? 0;
    return Math.max(1, String(total).length);
  }, [layout?.segments.length]);

  useEffect(() => {
    if (selected === null) {
      selectedOffsetRef.current = null;
      return;
    }
    if (selectedOffsetRef.current === selected.offset) {
      return;
    }
    selectedOffsetRef.current = selected.offset;
    const row = listRef.current?.querySelector<HTMLElement>(`[data-segment-offset="${selected.offset}"]`);
    row?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  useEffect(() => {
    if (isActive) {
      listRef.current?.focus();
    }
  }, [isActive]);

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (!layout || layout.segments.length === 0) {
      return;
    }
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") {
      return;
    }

    event.preventDefault();

    const currentIndex = selected
      ? layout.segments.findIndex((segment) => segment.offset === selected.offset)
      : -1;

    if (event.key === "ArrowDown") {
      const nextIndex =
        currentIndex < 0 ? 0 : Math.min(currentIndex + 1, layout.segments.length - 1);
      onSelect(layout.segments[nextIndex]);
      return;
    }

    const nextIndex =
      currentIndex < 0 ? layout.segments.length - 1 : Math.max(currentIndex - 1, 0);
    onSelect(layout.segments[nextIndex]);
  }

  function handleSelect(segment: Segment) {
    onSelect(segment);
    listRef.current?.focus();
  }

  if (!layout) {
    return <p className="segment-list-empty">Load a file to inspect its segments.</p>;
  }

  if (layout.segments.length === 0) {
    return <p className="segment-list-empty">No segments found in this file.</p>;
  }

  return (
    <div className="segment-list-panel">
      <div
        ref={listRef}
        className="segment-list"
        role="listbox"
        tabIndex={0}
        aria-label="Memory layout segments"
        aria-activedescendant={
          selected ? `segment-option-${selected.offset}` : undefined
        }
        onKeyDown={handleKeyDown}
      >
        {layout.segments.map((segment, index) => {
          const isSelected = selected?.offset === segment.offset;
          const categoryLabel = CATEGORY_LABELS[segment.category] ?? segment.category;
          const categoryColor = CATEGORY_COLORS[segment.category] ?? "#777777";
          const number = `${String(index + 1).padStart(numberWidth, " ")}.`;

          return (
            <button
              key={`${segment.offset}-${segment.label}`}
              id={`segment-option-${segment.offset}`}
              type="button"
              role="option"
              aria-selected={isSelected}
              data-segment-offset={segment.offset}
              className={`segment-list-item${isSelected ? " segment-list-item-selected" : ""}`}
              title={`${segment.path_label}\n0x${segment.offset.toString(16)} – 0x${segment.end.toString(16)}\n${segment.edit_safety.reason}`}
              onClick={() => handleSelect(segment)}
            >
              <span className="segment-list-number">{number}</span>
              <span className="segment-list-mark" style={{ color: categoryColor }}>
                {segment.edit_safety.mark}
              </span>
              <span className="segment-list-label">{segment.label}</span>
              <span className="segment-list-meta">{formatBytes(segment.size)}</span>
              <span className="segment-list-category">{categoryLabel}</span>
            </button>
          );
        })}
      </div>
      <p className="segment-list-hint">Click a segment to inspect it. Use ↑ and ↓ to move selection.</p>
    </div>
  );
}
