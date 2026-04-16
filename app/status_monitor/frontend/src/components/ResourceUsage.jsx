import { useState } from "react";
import { Paper, Text, Group, Stack, Skeleton, UnstyledButton } from "@mantine/core";
import DonutChart, { DONUT_SIZE } from "./DonutChart";
import LegendItem from "./LegendItem";
import { GpuCapacitySummary, RamCapacitySummary } from "./CapacitySummary";
import useClipboard from "./useClipboard";
import {
  buildSlices,
  formatBytes,
  formatPct,
  DETECTOR_COLORS,
  FREE_COLOR,
  LOADING_COLOR,
  OTHER_COLOR,
} from "./chartUtils";

const MAX_VISIBLE_LEGEND_ITEMS = 8;
const COL_HEADER_STYLE = { whiteSpace: "nowrap", minWidth: 64, textAlign: "right" };

/** Sorts detectors by (deploy_time, detector_id) and assigns a stable color.
 *
 * Sorting by deploy time gives a useful visual ordering in the legend; the
 * secondary sort on id keeps color assignment deterministic when two detectors
 * were deployed at the exact same time.
 */
function prepareDetectors(resourceData, detectorDetails) {
  const nameMap = {};
  const deployTime = {};
  if (detectorDetails) {
    for (const [id, info] of Object.entries(detectorDetails)) {
      nameMap[id] = info.detector_name || id;
      deployTime[id] = info.deploy_time || "";
    }
  }

  const sorted = (resourceData.detectors || []).slice().sort((a, b) => {
    const timeCmp = (deployTime[a.detector_id] || "").localeCompare(deployTime[b.detector_id] || "");
    return timeCmp !== 0 ? timeCmp : a.detector_id.localeCompare(b.detector_id);
  });

  const colorMap = {};
  sorted.forEach((det, i) => {
    colorMap[det.detector_id] = DETECTOR_COLORS[i % DETECTOR_COLORS.length];
  });

  return { detectors: sorted, nameMap, colorMap };
}

/** Builds legend rows for detectors and for the three summary slices (loading,
 * other, free), shared across the VRAM and RAM donuts.
 */
function buildLegendRows({ detectors, nameMap, colorMap, vram, ram }) {
  const detectorRows = detectors.map((det) => ({
    sliceKey: `det:${det.detector_id}`,
    detectorId: det.detector_id,
    color: colorMap[det.detector_id],
    label: nameMap[det.detector_id] || det.detector_id,
    vramValue: formatBytes(det.total_vram_bytes || 0),
    vramPct: formatPct(det.total_vram_bytes || 0, vram.total),
    ramValue: formatBytes(det.total_ram_bytes || 0),
    ramPct: formatPct(det.total_ram_bytes || 0, ram.total),
  }));

  const systemRow = (sliceKey, color, label, vramBytes, ramBytes) => ({
    sliceKey,
    color,
    label,
    vramValue: formatBytes(vramBytes),
    vramPct: formatPct(vramBytes, vram.total),
    ramValue: formatBytes(ramBytes),
    ramPct: formatPct(ramBytes, ram.total),
  });

  const systemRows = [
    systemRow("summary:loading", LOADING_COLOR, "Loading Detector Models", vram.loading, ram.loading),
    systemRow("summary:other", OTHER_COLOR, "Other", vram.other, ram.other),
    systemRow("summary:free", FREE_COLOR, "Free", vram.free, ram.free),
  ];

  return { detectorRows, systemRows };
}

function ResourceUsageSkeleton() {
  return (
    <Paper shadow="xs" p="lg" radius="sm">
      <div className="resource-donuts-row">
        <Skeleton circle height={DONUT_SIZE} width={DONUT_SIZE} />
        <Skeleton circle height={DONUT_SIZE} width={DONUT_SIZE} />
      </div>
      <Stack gap="xs" mt="md">
        <Skeleton height={16} width="75%" />
        <Skeleton height={16} width="85%" />
        <Skeleton height={16} width="70%" />
      </Stack>
    </Paper>
  );
}

function Snackbar({ text }) {
  if (!text) return null;
  return (
    <Paper
      shadow="md"
      radius="sm"
      p="sm"
      style={{
        position: "fixed",
        bottom: 20,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 1000,
        backgroundColor: "#1f1d23",
      }}
    >
      <Text size="sm" c="white">{text}</Text>
    </Paper>
  );
}

/** The detector + system legend rendered below the two donuts. Hover state is
 * shared with the donuts via `hoveredSliceKey` so that hovering a legend row
 * highlights the matching chart slice and vice-versa.
 */
function Legend({ detectorRows, systemRows, hasVram, hoveredSliceKey, setHoveredSliceKey, onCopy }) {
  const [showAll, setShowAll] = useState(false);
  const hiddenCount = Math.max(0, detectorRows.length - MAX_VISIBLE_LEGEND_ITEMS);
  const visibleRows = showAll ? detectorRows : detectorRows.slice(0, MAX_VISIBLE_LEGEND_ITEMS);

  const rowHandlers = (sliceKey) => ({
    active: hoveredSliceKey === sliceKey,
    onHoverStart: () => setHoveredSliceKey(sliceKey),
    onHoverEnd: () => setHoveredSliceKey((prev) => (prev === sliceKey ? null : prev)),
  });

  return (
    <Stack gap="xs" mt="md">
      <div style={{ padding: "3px 6px" }}>
        <Group gap="xs" wrap="nowrap">
          <Text size="xs" c="gray.8" fw={600} style={{ flex: 1, minWidth: 0 }}>
            Detectors ({detectorRows.length})
          </Text>
          {hasVram && (
            <>
              <Text size="xs" c="gray.8" fw={600} style={COL_HEADER_STYLE}>VRAM</Text>
              <div style={{ minWidth: 48 }} />
            </>
          )}
          <Text size="xs" c="gray.8" fw={600} style={COL_HEADER_STYLE}>RAM</Text>
          <div style={{ minWidth: 48 }} />
        </Group>
      </div>

      {visibleRows.map((row, i) => (
        <LegendItem
          key={row.sliceKey}
          {...row}
          hasVram={hasVram}
          striped={i % 2 === 1}
          onClick={() => onCopy(row.detectorId)}
          {...rowHandlers(row.sliceKey)}
        />
      ))}

      {hiddenCount > 0 && (
        <UnstyledButton
          onClick={() => setShowAll((v) => !v)}
          style={{ color: "#165a8a", fontSize: "0.85em", textAlign: "left" }}
        >
          {showAll ? "Show fewer detectors" : `Show all detectors (+${hiddenCount})`}
        </UnstyledButton>
      )}

      <Stack gap={2} mt={6}>
        <Text size="xs" c="gray.8" fw={600} style={{ padding: "3px 6px" }}>System</Text>
        {systemRows.map((row) => (
          <LegendItem
            key={row.sliceKey}
            {...row}
            hasVram={hasVram}
            {...rowHandlers(row.sliceKey)}
          />
        ))}
      </Stack>
    </Stack>
  );
}

/** Top-level resource-usage panel: two side-by-side donuts (VRAM + RAM) and a
 * shared legend, backed by the `/status/resources.json` payload.
 */
export default function ResourceUsage({ resourceData, detectorDetails, loading }) {
  const [hoveredSliceKey, setHoveredSliceKey] = useState(null);
  const { copy, snackbarText } = useClipboard({
    successMessage: (id) => `Detector ID copied (${id})`,
    errorMessage: "Failed to copy detector ID",
  });

  if (loading && !resourceData) return <ResourceUsageSkeleton />;
  if (!resourceData) return null;
  if (resourceData.error) {
    return (
      <Paper shadow="xs" p="md" radius="sm">
        <Text c="gray.8" fs="italic">{resourceData.error}</Text>
      </Paper>
    );
  }

  const observedGpus = resourceData.observed_gpus || [];
  const hasVram = observedGpus.length > 0;
  const hasRam = (resourceData.total_ram_bytes || 0) > 0;

  const vram = {
    total: resourceData.total_vram_bytes || 0,
    used: resourceData.used_vram_bytes || 0,
    loading: resourceData.loading_vram_bytes || 0,
  };
  const ram = {
    total: resourceData.total_ram_bytes || 0,
    used: resourceData.used_ram_bytes || 0,
    loading: resourceData.loading_ram_bytes || 0,
    evictionPct: resourceData.ram_eviction_threshold_pct ?? null,
  };

  const { detectors, nameMap, colorMap } = prepareDetectors(resourceData, detectorDetails);

  // Zero-state VRAM chart: render a 100%-free donut with a phantom 1-byte total.
  // This keeps the donut's slice structure stable across the has-VRAM /
  // no-VRAM transition so recharts animates smoothly (see DonutChart.jsx).
  const vramSlices = buildSlices({
    detectors: hasVram ? detectors : [],
    detNameMap: nameMap,
    totalBytes: hasVram ? vram.total : 1,
    usedBytes: hasVram ? vram.used : 0,
    loadingBytes: hasVram ? vram.loading : 0,
    colorMap,
    bytesKey: "total_vram_bytes",
    resourceLabel: "VRAM",
  });

  const ramSlices = hasRam
    ? buildSlices({
        detectors,
        detNameMap: nameMap,
        totalBytes: ram.total,
        usedBytes: ram.used,
        loadingBytes: ram.loading,
        colorMap,
        bytesKey: "total_ram_bytes",
        resourceLabel: "RAM",
      })
    : null;

  const { detectorRows, systemRows } = buildLegendRows({
    detectors,
    nameMap,
    colorMap,
    vram: { total: vram.total, loading: vram.loading, other: vramSlices.otherBytes, free: vramSlices.freeBytes },
    ram: {
      total: ram.total,
      loading: ram.loading,
      other: ramSlices?.otherBytes ?? 0,
      free: ramSlices?.freeBytes ?? 0,
    },
  });

  const onSliceClick = (slice) => {
    if (slice?.type === "detector") copy(slice.detectorId);
  };

  return (
    <Paper shadow="xs" p="lg" radius="sm">
      <div className="resource-donuts-row">
        <Stack gap="xs" align="center">
          <Text size="lg" fw={700} c="gray.8">VRAM</Text>
          {hasVram ? (
            <GpuCapacitySummary observedGpus={observedGpus} totalBytes={vram.total} usedBytes={vram.used} />
          ) : (
            <Text size="sm" c="gray.6">No GPU discovered</Text>
          )}
          <DonutChart
            slices={vramSlices.slices}
            centerText={hasVram ? `${((vram.used / vram.total) * 100).toFixed(0)}%` : "Unknown"}
            activeSliceKey={hoveredSliceKey}
            onSliceHover={setHoveredSliceKey}
            onSliceClick={onSliceClick}
          />
        </Stack>

        {hasRam && (
          <Stack gap="xs" align="center">
            <Text size="lg" fw={700} c="gray.8">RAM</Text>
            <RamCapacitySummary totalBytes={ram.total} usedBytes={ram.used} />
            <DonutChart
              slices={ramSlices.slices}
              centerText={`${((ram.used / ram.total) * 100).toFixed(0)}%`}
              activeSliceKey={hoveredSliceKey}
              onSliceHover={setHoveredSliceKey}
              onSliceClick={onSliceClick}
              evictionThresholdPct={ram.evictionPct}
            />
          </Stack>
        )}
      </div>

      <Legend
        detectorRows={detectorRows}
        systemRows={systemRows}
        hasVram={hasVram}
        hoveredSliceKey={hoveredSliceKey}
        setHoveredSliceKey={setHoveredSliceKey}
        onCopy={copy}
      />

      <Snackbar text={snackbarText} />
    </Paper>
  );
}
