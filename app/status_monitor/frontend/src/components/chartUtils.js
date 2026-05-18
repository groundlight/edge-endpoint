// Shared utilities for the resource-usage donut charts: formatters, color palette,
// and the pure function that converts per-detector bytes into donut slices.

export const FREE_COLOR = "#E0E0E0";
export const LOADING_COLOR = "#555555";
export const OTHER_COLOR = "#B0B0B0";
export const EDGE_ENDPOINT_COLOR = "#000000";

/** Human-friendly descriptions for each system-level slice, keyed by the
 * stable `sliceKey` produced by `buildSlices`. Surfaced in the donut tooltip
 * and as a hover tooltip on the corresponding legend row. Detector slices
 * intentionally have no entry here.
 */
export const SYSTEM_SLICE_HELP = {
  "summary:loading": "Detectors that are initializing or updating",
  "summary:edge-endpoint": "Platform overhead — all Edge Endpoint processes other than detectors",
  "summary:other": "Resources used by everything except the Edge Endpoint, such as the operating system and other applications",
  "summary:free": "Unused capacity",
};

export function getSliceHelpText(sliceKey) {
  return SYSTEM_SLICE_HELP[sliceKey] || null;
}

/** Minimum number of detector slots pre-allocated in the donut chart.
 * The chart pads unused slots with zero-byte placeholders so that recharts
 * animates positional changes smoothly as detectors appear and disappear.
 * See DonutChart.jsx for details.
 */
export const MIN_DETECTOR_SLOTS = 30;

/** Deterministic HSL palette with high adjacent contrast. */
export function buildDetectorPalette(size = MIN_DETECTOR_SLOTS) {
  const step = 11; // coprime with 30; keeps adjacent hues visually distinct
  const saturation = 65;
  const lightness = 52;
  return Array.from({ length: size }, (_, i) => {
    const hue = (((i * step) % size) * 360) / size;
    return `hsl(${hue.toFixed(0)} ${saturation}% ${lightness}%)`;
  });
}

export const DETECTOR_COLORS = buildDetectorPalette();

export function formatBytes(bytes) {
  if (bytes == null) return "--";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

export function formatPct(bytes, totalBytes) {
  if (!totalBytes) return "0.0%";
  return `${((bytes / totalBytes) * 100).toFixed(1)}%`;
}

export function formatPctInt(bytes, totalBytes) {
  if (!totalBytes) return "0%";
  return `${Math.round((bytes / totalBytes) * 100)}%`;
}

/** Builds donut slices for one resource (VRAM or RAM).
 *
 * Returns `{ slices, otherBytes, freeBytes }`. The slices array always ends
 * with three summary slices (loading / other / free), which the donut chart
 * relies on for stable positional animation.
 *
 * `resourceKey` selects which sub-object on each detector to read (e.g.
 * "gpu.vram_bytes" or "ram_bytes"); each detector is expected to have that
 * key with a nested `total` field.
 */
export function buildSlices({
  detectors,
  detNameMap,
  totalBytes,
  usedBytes,
  loadingBytes,
  edgeEndpointBytes = 0,
  colorMap,
  resourceKey,
  resourceLabel,
}) {
  const pct = (bytes) => (totalBytes ? (bytes / totalBytes) * 100 : 0);
  const slices = [];
  let accountedBytes = 0;

  const getResource = (det) => resourceKey.split(".").reduce((value, key) => value?.[key], det);

  for (const det of detectors) {
    const bytes = getResource(det)?.total || 0;
    accountedBytes += bytes;
    slices.push({
      sliceKey: `det:${det.detector_id}`,
      type: "detector",
      detectorId: det.detector_id,
      label: detNameMap[det.detector_id] || det.detector_id,
      bytes,
      color: colorMap[det.detector_id] || "#999",
      pct: pct(bytes),
      resourceLabel,
    });
  }

  accountedBytes += loadingBytes;
  slices.push({
    sliceKey: "summary:loading",
    type: "summary",
    label: "Loading Detector Models",
    bytes: loadingBytes,
    color: LOADING_COLOR,
    pct: pct(loadingBytes),
    resourceLabel,
  });

  accountedBytes += edgeEndpointBytes;
  slices.push({
    sliceKey: "summary:edge-endpoint",
    type: "summary",
    label: "Edge Endpoint",
    bytes: edgeEndpointBytes,
    color: EDGE_ENDPOINT_COLOR,
    pct: pct(edgeEndpointBytes),
    resourceLabel,
  });

  const otherBytes = Math.max(0, usedBytes - accountedBytes);
  slices.push({
    sliceKey: "summary:other",
    type: "summary",
    label: "Other",
    bytes: otherBytes,
    color: OTHER_COLOR,
    pct: pct(otherBytes),
    resourceLabel,
  });

  const freeBytes = Math.max(0, totalBytes - usedBytes);
  slices.push({
    sliceKey: "summary:free",
    type: "summary",
    label: "Free",
    bytes: freeBytes,
    color: FREE_COLOR,
    pct: pct(freeBytes),
    resourceLabel,
  });

  return { slices, otherBytes, freeBytes };
}
