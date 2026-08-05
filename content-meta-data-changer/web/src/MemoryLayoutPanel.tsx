import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LayoutResult, Segment } from "./api/client";
import SegmentDetailPanel from "./SegmentDetailPanel";
import SegmentListPanel from "./SegmentListPanel";

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

const EDIT_SAFETY_MARKS: Record<string, string> = {
  safe: "✓",
  caution: "⚠",
  unsafe: "✕",
};

const EDIT_SAFETY_LABELS: Record<string, string> = {
  safe: "Safe",
  caution: "Caution",
  unsafe: "Unsafe",
};

const EDIT_SAFETY_COLORS: Record<string, string> = {
  safe: "#43a047",
  caution: "#ffa726",
  unsafe: "#e53935",
};

const MAP_HEIGHT = 28;
const SCROLL_SLIDER_MAX = 1000;
const MIN_BYTES_PER_PIXEL = 1;
const MAX_BYTES_PER_PIXEL = 1024 * 1024;
const DEFAULT_BYTES_PER_PIXEL = 4096;

type MemoryLayoutTab = "map" | "list";

function sliderToBytesPerPixel(value: number): number {
  const minLog = Math.log(MIN_BYTES_PER_PIXEL);
  const maxLog = Math.log(MAX_BYTES_PER_PIXEL);
  const ratio = value / 1000;
  return Math.exp(minLog + (maxLog - minLog) * ratio);
}

function bytesPerPixelToSlider(bytesPerPixel: number): number {
  const minLog = Math.log(MIN_BYTES_PER_PIXEL);
  const maxLog = Math.log(MAX_BYTES_PER_PIXEL);
  const clamped = Math.max(MIN_BYTES_PER_PIXEL, Math.min(MAX_BYTES_PER_PIXEL, bytesPerPixel));
  const ratio = (Math.log(clamped) - minLog) / (maxLog - minLog);
  return Math.round(ratio * 1000);
}

function clampBytesPerPixel(bytesPerPixel: number): number {
  return Math.max(MIN_BYTES_PER_PIXEL, Math.min(MAX_BYTES_PER_PIXEL, bytesPerPixel));
}

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

function formatScale(bytesPerPixel: number): string {
  if (bytesPerPixel < 1024) {
    return `1 px = ${bytesPerPixel.toFixed(0)} B`;
  }
  if (bytesPerPixel < 1024 * 1024) {
    return `1 px = ${(bytesPerPixel / 1024).toFixed(1)} KB`;
  }
  return `1 px = ${(bytesPerPixel / (1024 * 1024)).toFixed(1)} MB`;
}

function computeMaxStartByte(fileSize: number, viewportWidth: number, bytesPerPixel: number): number {
  const visibleBytes = viewportWidth * bytesPerPixel;
  return Math.max(0, fileSize - visibleBytes);
}

function startByteFromScrollSlider(scrollSlider: number, maxStartByte: number): number {
  if (maxStartByte <= 0) {
    return 0;
  }
  return Math.floor((scrollSlider / SCROLL_SLIDER_MAX) * maxStartByte);
}

function scrollSliderFromStartByte(startByte: number, maxStartByte: number): number {
  if (maxStartByte <= 0) {
    return 0;
  }
  return Math.round((Math.max(0, Math.min(startByte, maxStartByte)) / maxStartByte) * SCROLL_SLIDER_MAX);
}

function visibleSegments(segments: readonly Segment[], startByte: number, endByte: number): Segment[] {
  return segments.filter((segment) => segment.end > startByte && segment.offset < endByte);
}

type MemoryLayoutPanelProps = {
  fileId: string | null;
  layout: LayoutResult | null;
  selected: Segment | null;
  onSelect: (segment: Segment | null) => void;
};

export default function MemoryLayoutPanel({ fileId, layout, selected, onSelect }: MemoryLayoutPanelProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const initializedFileKeyRef = useRef<string | null>(null);
  const [tab, setTab] = useState<MemoryLayoutTab>("map");
  const [zoomSlider, setZoomSlider] = useState(bytesPerPixelToSlider(DEFAULT_BYTES_PER_PIXEL));
  const [scrollSlider, setScrollSlider] = useState(0);
  const [hovered, setHovered] = useState<Segment | null>(null);
  const [viewportWidth, setViewportWidth] = useState(1);

  const bytesPerPixel = useMemo(
    () => clampBytesPerPixel(sliderToBytesPerPixel(zoomSlider)),
    [zoomSlider],
  );

  const maxStartByte = useMemo(() => {
    if (!layout) {
      return 0;
    }
    return computeMaxStartByte(layout.file_size, viewportWidth, bytesPerPixel);
  }, [layout, viewportWidth, bytesPerPixel]);

  const startByte = useMemo(
    () => startByteFromScrollSlider(scrollSlider, maxStartByte),
    [scrollSlider, maxStartByte],
  );

  const endByte = useMemo(() => {
    if (!layout) {
      return 0;
    }
    return Math.min(layout.file_size, Math.ceil(startByte + viewportWidth * bytesPerPixel));
  }, [layout, startByte, viewportWidth, bytesPerPixel]);

  const activeSegment = tab === "map" ? hovered ?? selected : selected;
  const canScroll = maxStartByte > 0;

  const updateViewportWidth = useCallback(() => {
    const element = viewportRef.current;
    if (!element) {
      return;
    }
    setViewportWidth(Math.max(1, element.clientWidth));
  }, []);

  useEffect(() => {
    updateViewportWidth();
    const element = viewportRef.current;
    if (!element) {
      return;
    }
    const observer = new ResizeObserver(updateViewportWidth);
    observer.observe(element);
    return () => observer.disconnect();
  }, [updateViewportWidth, tab]);

  useEffect(() => {
    if (!layout || viewportWidth <= 1) {
      return;
    }
    const fileKey = `${fileId ?? "none"}:${layout.file_size}`;
    if (initializedFileKeyRef.current === fileKey) {
      return;
    }
    initializedFileKeyRef.current = fileKey;
    setScrollSlider(0);
    setZoomSlider(bytesPerPixelToSlider(clampBytesPerPixel(layout.file_size / viewportWidth)));
  }, [fileId, layout, viewportWidth]);

  const drawViewport = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !layout || viewportWidth <= 0 || tab !== "map") {
      return;
    }
    const context = canvas.getContext("2d");
    if (!context) {
      return;
    }

    const pixelRatio = window.devicePixelRatio || 1;
    const canvasWidth = Math.max(1, Math.floor(viewportWidth));
    const canvasHeight = MAP_HEIGHT;

    canvas.width = Math.floor(canvasWidth * pixelRatio);
    canvas.height = Math.floor(canvasHeight * pixelRatio);
    canvas.style.width = `${canvasWidth}px`;
    canvas.style.height = `${canvasHeight}px`;
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

    context.clearRect(0, 0, canvasWidth, canvasHeight);
    context.fillStyle = "#1e1e1e";
    context.fillRect(0, 0, canvasWidth, canvasHeight);

    for (const segment of visibleSegments(layout.segments, startByte, endByte)) {
      const drawStart = Math.max(segment.offset, startByte);
      const drawEnd = Math.min(segment.end, endByte);
      const x = Math.floor((drawStart - startByte) / bytesPerPixel);
      const width = Math.max(1, Math.ceil((drawEnd - drawStart) / bytesPerPixel));
      const isActive =
        selected?.offset === segment.offset ||
        hovered?.offset === segment.offset;
      const baseColor = CATEGORY_COLORS[segment.category] ?? "#777777";
      context.fillStyle = isActive ? lightenColor(baseColor) : baseColor;
      context.fillRect(x, 0, width, canvasHeight);
    }

    context.strokeStyle = "#555555";
    context.strokeRect(0, 0, Math.max(0, canvasWidth - 1), canvasHeight - 1);
  }, [layout, viewportWidth, startByte, endByte, bytesPerPixel, selected, hovered, tab]);

  useEffect(() => {
    drawViewport();
  }, [drawViewport]);

  function segmentAtOffset(offset: number): Segment | null {
    if (!layout) {
      return null;
    }
    const clamped = Math.max(0, Math.min(offset, layout.file_size - 1));
    return layout.segments.find((item) => item.offset <= clamped && clamped < item.end) ?? null;
  }

  function offsetAtPointer(clientX: number): number | null {
    if (!layout || !canvasRef.current) {
      return null;
    }
    const rect = canvasRef.current.getBoundingClientRect();
    const localX = clientX - rect.left;
    if (localX < 0 || localX > rect.width) {
      return null;
    }
    return Math.floor(startByte + localX * bytesPerPixel);
  }

  function setScrollFromStartByte(nextStartByte: number) {
    setScrollSlider(scrollSliderFromStartByte(nextStartByte, maxStartByte));
  }

  function handleMapPointer(event: React.MouseEvent<HTMLCanvasElement> | React.TouchEvent<HTMLCanvasElement>) {
    const clientX = "touches" in event ? event.touches[0]?.clientX ?? event.changedTouches[0]?.clientX : event.clientX;
    if (clientX === undefined) {
      return;
    }
    const offset = offsetAtPointer(clientX);
    if (offset === null) {
      return;
    }
    onSelect(segmentAtOffset(offset));
  }

  function handleMapWheel(event: React.WheelEvent<HTMLDivElement>) {
    if (!layout) {
      return;
    }

    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      const centerByte = startByte + (viewportWidth * bytesPerPixel) / 2;
      const factor = event.deltaY < 0 ? 0.85 : 1.18;
      const nextBytesPerPixel = clampBytesPerPixel(bytesPerPixel * factor);
      const nextMaxStart = computeMaxStartByte(layout.file_size, viewportWidth, nextBytesPerPixel);
      const nextStartByte = Math.max(0, centerByte - (viewportWidth * nextBytesPerPixel) / 2);

      setZoomSlider(bytesPerPixelToSlider(nextBytesPerPixel));
      setScrollSlider(scrollSliderFromStartByte(Math.min(nextStartByte, nextMaxStart), nextMaxStart));
      return;
    }

    if (!canScroll) {
      return;
    }

    if (event.deltaX !== 0 || event.shiftKey) {
      event.preventDefault();
      const deltaBytes = (event.deltaX || event.deltaY) * bytesPerPixel;
      setScrollFromStartByte(startByte + deltaBytes);
    }
  }

  function fitToWidth() {
    if (!layout) {
      return;
    }
    setZoomSlider(bytesPerPixelToSlider(clampBytesPerPixel(layout.file_size / viewportWidth)));
    setScrollSlider(0);
  }

  function handleZoomChange(value: number) {
    if (!layout) {
      setZoomSlider(value);
      return;
    }

    const centerByte = startByte + (viewportWidth * bytesPerPixel) / 2;
    const nextBytesPerPixel = clampBytesPerPixel(sliderToBytesPerPixel(value));
    const nextMaxStart = computeMaxStartByte(layout.file_size, viewportWidth, nextBytesPerPixel);
    const nextStartByte = Math.max(0, centerByte - (viewportWidth * nextBytesPerPixel) / 2);

    setZoomSlider(bytesPerPixelToSlider(nextBytesPerPixel));
    setScrollSlider(scrollSliderFromStartByte(Math.min(nextStartByte, nextMaxStart), nextMaxStart));
  }

  function handleTabChange(nextTab: MemoryLayoutTab) {
    setTab(nextTab);
    if (nextTab === "map") {
      setHovered(null);
    }
  }

  return (
    <div className="memory-layout">
      <p className="memory-layout-info">
        {layout
          ? activeSegment
            ? `${activeSegment.label} | ${CATEGORY_LABELS[activeSegment.category] ?? activeSegment.category} | ${activeSegment.edit_safety.mark} ${activeSegment.edit_safety.label} | 0x${activeSegment.offset.toString(16)} | ${formatBytes(activeSegment.size)}`
            : `File size: ${formatBytes(layout.file_size)} | Segments: ${layout.segments.length}`
          : "Load a file to inspect its memory map."}
      </p>

      <div className="memory-layout-tabs" role="tablist" aria-label="Memory layout views">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "map"}
          className={`memory-layout-tab${tab === "map" ? " memory-layout-tab-active" : ""}`}
          onClick={() => handleTabChange("map")}
        >
          Map
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "list"}
          className={`memory-layout-tab${tab === "list" ? " memory-layout-tab-active" : ""}`}
          onClick={() => handleTabChange("list")}
        >
          List
        </button>
      </div>

      <div className="memory-layout-tab-panel">
        {tab === "map" ? (
          <>
            <div className="memory-layout-legend">
              {Object.entries(CATEGORY_LABELS).map(([category, label]) => (
                <span key={category} className="memory-layout-legend-item">
                  <span className="memory-layout-swatch" style={{ backgroundColor: CATEGORY_COLORS[category] }} />
                  {label}
                </span>
              ))}
            </div>
            <div className="memory-layout-legend memory-layout-legend-safety">
              <span className="memory-layout-legend-caption">Edit safety:</span>
              {Object.entries(EDIT_SAFETY_LABELS).map(([level, label]) => (
                <span key={level} className="memory-layout-legend-item">
                  <span className="memory-layout-mark" style={{ color: EDIT_SAFETY_COLORS[level] }}>
                    {EDIT_SAFETY_MARKS[level]}
                  </span>
                  {label}
                </span>
              ))}
            </div>

            <div ref={viewportRef} className="layout-map-viewport" onWheel={handleMapWheel}>
              <canvas
                ref={canvasRef}
                className="layout-map"
                onClick={handleMapPointer}
                onMouseMove={(event) => {
                  const offset = offsetAtPointer(event.clientX);
                  setHovered(offset === null ? null : segmentAtOffset(offset));
                }}
                onMouseLeave={() => setHovered(null)}
                onTouchEnd={handleMapPointer}
              />
            </div>

            <div className="memory-layout-scroll-control">
              <label className="memory-layout-scroll-label" htmlFor="memory-layout-scroll">
                Scroll
              </label>
              <input
                id="memory-layout-scroll"
                className="memory-layout-scroll"
                type="range"
                min={0}
                max={SCROLL_SLIDER_MAX}
                step={1}
                value={scrollSlider}
                disabled={!canScroll}
                onChange={(event) => setScrollSlider(Number(event.target.value))}
              />
              <span className="memory-layout-scroll-value">
                {canScroll
                  ? `0x${startByte.toString(16)} – 0x${endByte.toString(16)}`
                  : "Full file visible"}
              </span>
            </div>

            <div className="memory-layout-controls">
              <label className="memory-layout-zoom-label" htmlFor="memory-layout-zoom">
                Zoom
              </label>
              <input
                id="memory-layout-zoom"
                className="memory-layout-zoom"
                type="range"
                min={0}
                max={1000}
                value={zoomSlider}
                onChange={(event) => handleZoomChange(Number(event.target.value))}
              />
              <span className="memory-layout-scale">{formatScale(bytesPerPixel)}</span>
              <button type="button" onClick={fitToWidth}>
                Fit Width
              </button>
            </div>

            <p className="memory-layout-hint">
              Use the scroll slider below the map, or Shift + scroll over the map. Ctrl or Cmd + scroll to zoom.
            </p>
          </>
        ) : (
          <SegmentListPanel layout={layout} selected={selected} onSelect={onSelect} isActive={tab === "list"} />
        )}
      </div>

      {fileId && selected && <SegmentDetailPanel fileId={fileId} segment={selected} />}
    </div>
  );
}

function lightenColor(hex: string): string {
  const value = hex.replace("#", "");
  if (value.length !== 6) {
    return hex;
  }
  const red = Math.min(255, parseInt(value.slice(0, 2), 16) + 40);
  const green = Math.min(255, parseInt(value.slice(2, 4), 16) + 40);
  const blue = Math.min(255, parseInt(value.slice(4, 6), 16) + 40);
  return `rgb(${red}, ${green}, ${blue})`;
}
