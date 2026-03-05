import { useEffect, useState } from "react";
import { Paper, Text, Group, Stack, Skeleton, UnstyledButton } from "@mantine/core";
import DonutChart, { DONUT_SIZE } from "./DonutChart";

/** Builds a deterministic detector color palette with high adjacent contrast. */
function buildDetectorPalette(size = 30) {
  const step = 11; // coprime with 30; keeps adjacent colors far apart
  const saturation = 65;
  const lightness = 52;
  return Array.from({ length: size }, (_, i) => {
    const hue = (((i * step) % size) * 360) / size;
    return `hsl(${hue.toFixed(0)} ${saturation}% ${lightness}%)`;
  });
}

const COLORS = buildDetectorPalette(30);
const FREE_COLOR = "#E0E0E0";
const LOADING_COLOR = "#555555";
const OTHER_COLOR = "#B0B0B0";
const MAX_VISIBLE_LEGEND_ITEMS = 8;

/** Formats bytes as GB/MB text for legend and summaries. */
function formatBytes(bytes) {
  if (bytes == null) return "--";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

/** Formats bytes as a percentage of total capacity. */
function formatPct(bytes, totalBytes) {
  if (!totalBytes) return "0.0%";
  return `${((bytes / totalBytes) * 100).toFixed(1)}%`;
}

/** Formats bytes as an integer percentage for compact summaries. */
function formatPctInt(bytes, totalBytes) {
  if (!totalBytes) return "0%";
  return `${Math.round((bytes / totalBytes) * 100)}%`;
}

/** Renders GPU model and capacity text above the chart. */
function GpuCapacitySummary({ observedGpus, totalBytes, usedBytes }) {
  const gpus = (observedGpus || []).filter((g) => g?.name);
  const getTotal = (gpu) => gpu?.total_vram_bytes ?? gpu?.total_bytes ?? 0;
  const getUsed = (gpu) => gpu?.used_vram_bytes ?? gpu?.used_bytes ?? 0;

  if (gpus.length === 1) {
    const gpu = gpus[0];
    const gpuTotal = getTotal(gpu);
    const gpuUsed = getUsed(gpu);
    return (
      <Text size="sm" fw={500}>
        {gpu.name} ({formatBytes(gpuUsed)} / {formatBytes(gpuTotal)} used, {formatPctInt(gpuUsed, gpuTotal)})
      </Text>
    );
  }
  if (gpus.length > 1) {
    const totalGpuBytes = gpus.reduce((sum, gpu) => sum + getTotal(gpu), 0);
    const usedGpuBytes = gpus.reduce((sum, gpu) => sum + getUsed(gpu), 0);
    return (
      <Stack gap={2}>
        <Text size="sm" fw={500}>
          Total GPU Usage: {formatBytes(usedGpuBytes)} / {formatBytes(totalGpuBytes)} used,{" "}
          {formatPctInt(usedGpuBytes, totalGpuBytes)}
        </Text>
        {gpus.map((gpu, i) => (
          <Text key={`${gpu.name}-${i}`} size="xs" c="dimmed">
            GPU {gpu.index ?? i}: {gpu.name} ({formatBytes(getUsed(gpu))} / {formatBytes(getTotal(gpu))} used,{" "}
            {formatPctInt(getUsed(gpu), getTotal(gpu))})
          </Text>
        ))}
      </Stack>
    );
  }
  return (
    <Text size="sm" fw={500}>
      Total GPU Usage: {formatBytes(usedBytes)} / {formatBytes(totalBytes)} used, {formatPctInt(usedBytes, totalBytes)}
    </Text>
  );
}

/** Renders one row in the detector/system legend. */
function LegendItem({
  color,
  label,
  value,
  pct,
  striped = false,
  active = false,
  onHoverStart,
  onHoverEnd,
  onClick,
}) {
  const clickable = Boolean(onClick);
  return (
    <div
      style={{
        padding: "3px 6px",
        borderRadius: 4,
        backgroundColor: active ? "#e9f2ff" : striped ? "#f7f8fa" : "transparent",
        border: active ? "1px solid #7aa7e0" : "1px solid transparent",
        cursor: clickable ? "pointer" : "default",
      }}
      onPointerEnter={() => onHoverStart?.()}
      onPointerLeave={() => onHoverEnd?.()}
      onClick={onClick}
    >
      <Group gap="xs" wrap="nowrap">
        <div
          style={{
            width: 14,
            height: 14,
            borderRadius: 3,
            backgroundColor: color,
            flexShrink: 0,
          }}
        />
        <Text size="sm" style={{ flex: 1 }}>
          {label}
        </Text>
        <Text size="sm" fw={500} style={{ whiteSpace: "nowrap" }}>
          {value}
        </Text>
        <Text size="sm" c="dimmed" style={{ whiteSpace: "nowrap", minWidth: 56, textAlign: "right" }}>
          {pct}
        </Text>
      </Group>
    </div>
  );
}

/** Renders a loading skeleton matching the donut layout. */
function VramUsageSkeleton() {
  return (
    <Paper shadow="xs" p="lg" radius="sm">
      <Group gap="xl" align="center">
        <Skeleton circle height={DONUT_SIZE} width={DONUT_SIZE} />
        <Stack gap="xs" style={{ flex: 1 }}>
          <Skeleton height={16} width="75%" />
          <Skeleton height={16} width="85%" />
          <Skeleton height={16} width="70%" />
          <Skeleton height={16} width="80%" />
          <Skeleton height={16} width="65%" />
        </Stack>
      </Group>
    </Paper>
  );
}

/** Renders detector VRAM donut, legends, and copy interactions. */
export default function VramUsage({ gpuData, detectorDetails, loading }) {
  const [showAllLegendItems, setShowAllLegendItems] = useState(false);
  const [hoveredSliceKey, setHoveredSliceKey] = useState(null);
  const [snackbarText, setSnackbarText] = useState(null);

  useEffect(() => {
    if (!snackbarText) return undefined;
    const timer = setTimeout(() => setSnackbarText(null), 2200);
    return () => clearTimeout(timer);
  }, [snackbarText]);

  const copyDetectorId = async (detectorId) => {
    if (!detectorId) return;
    try {
      await navigator.clipboard.writeText(detectorId);
      setSnackbarText(`Detector ID copied (${detectorId})`);
    } catch {
      try {
        const textarea = document.createElement("textarea");
        textarea.value = detectorId;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "absolute";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.select();
        const ok = document.execCommand("copy");
        document.body.removeChild(textarea);
        setSnackbarText(ok ? `Detector ID copied (${detectorId})` : "Failed to copy detector ID");
      } catch {
        setSnackbarText("Failed to copy detector ID");
      }
    }
  };

  if (loading && !gpuData) return <VramUsageSkeleton />;
  if (!gpuData) return null;

  if (gpuData.error) {
    return (
      <Paper shadow="xs" p="md" radius="sm">
        <Text c="dimmed" fs="italic">
          {gpuData.error}
        </Text>
      </Paper>
    );
  }

  const totalBytes = gpuData.total_vram_bytes || 0;
  if (totalBytes === 0) {
    return (
      <Paper shadow="xs" p="md" radius="sm">
        <Text c="dimmed" fs="italic">
          No GPU data available.
        </Text>
      </Paper>
    );
  }

  const detNameMap = {};
  const detDeployTime = {};
  if (detectorDetails) {
    for (const [id, info] of Object.entries(detectorDetails)) {
      detNameMap[id] = info.detector_name || id;
      detDeployTime[id] = info.deploy_time || "";
    }
  }

  const detectors = (gpuData.detectors || []).slice().sort((a, b) => {
    const timeCmp = (detDeployTime[a.detector_id] || "").localeCompare(detDeployTime[b.detector_id] || "");
    return timeCmp !== 0 ? timeCmp : a.detector_id.localeCompare(b.detector_id);
  });
  const usedBytes = gpuData.used_vram_bytes || 0;
  const loadingVramBytes = gpuData.loading_vram_bytes || 0;
  const observedGpus = gpuData.observed_gpus || [];
  const slices = [];
  const detectorLegend = [];
  let accountedBytes = 0;

  detectors.forEach((det, i) => {
    const color = COLORS[i % COLORS.length];
    const label = detNameMap[det.detector_id] || det.detector_id;
    const bytes = det.total_vram_bytes || 0;
    accountedBytes += bytes;
    slices.push({
      sliceKey: `det:${det.detector_id}`,
      type: "detector",
      detectorId: det.detector_id,
      name: label,
      label,
      bytes,
      color,
      pct: (bytes / totalBytes) * 100,
    });
    detectorLegend.push({
      sliceKey: `det:${det.detector_id}`,
      detectorId: det.detector_id,
      color,
      label,
      value: formatBytes(bytes),
      pct: formatPct(bytes, totalBytes),
    });
  });

  accountedBytes += loadingVramBytes;
  slices.push({
    sliceKey: "summary:loading",
    type: "summary",
    label: "Loading Detector Models",
    bytes: loadingVramBytes,
    color: LOADING_COLOR,
    pct: (loadingVramBytes / totalBytes) * 100,
  });

  const otherBytes = Math.max(0, usedBytes - accountedBytes);
  slices.push({
    sliceKey: "summary:other",
    type: "summary",
    label: "Other",
    bytes: otherBytes,
    color: OTHER_COLOR,
    pct: (otherBytes / totalBytes) * 100,
  });

  const freeBytes = Math.max(0, totalBytes - usedBytes);
  slices.push({
    sliceKey: "summary:free",
    type: "summary",
    label: "Free",
    bytes: freeBytes,
    color: FREE_COLOR,
    pct: (freeBytes / totalBytes) * 100,
  });

  const usedPct = `${((usedBytes / totalBytes) * 100).toFixed(0)}%`;
  const activeSliceKey = hoveredSliceKey;
  const hiddenCount = Math.max(0, detectorLegend.length - MAX_VISIBLE_LEGEND_ITEMS);
  const visibleLegend = showAllLegendItems
    ? detectorLegend
    : detectorLegend.slice(0, MAX_VISIBLE_LEGEND_ITEMS);
  const systemLegend = [];
  systemLegend.push({
    sliceKey: "summary:loading",
    color: LOADING_COLOR,
    label: "Loading Detector Models",
    value: formatBytes(loadingVramBytes),
    pct: formatPct(loadingVramBytes, totalBytes),
  });
  systemLegend.push({
    sliceKey: "summary:other",
    color: OTHER_COLOR,
    label: "Other",
    value: formatBytes(otherBytes),
    pct: formatPct(otherBytes, totalBytes),
  });
  systemLegend.push({
    sliceKey: "summary:free",
    color: FREE_COLOR,
    label: "Free",
    value: formatBytes(freeBytes),
    pct: formatPct(freeBytes, totalBytes),
  });

  return (
    <Paper shadow="xs" p="lg" radius="sm">
      <Group gap="xl" align="flex-start">
        <Stack gap="xs">
          <GpuCapacitySummary observedGpus={observedGpus} totalBytes={totalBytes} usedBytes={usedBytes} />
          <DonutChart
            slices={slices}
            centerText={usedPct}
            activeSliceKey={activeSliceKey}
            onSliceHover={(key) => setHoveredSliceKey(key)}
            onSliceClick={(slice) => {
              if (slice?.type !== "detector") return;
              copyDetectorId(slice.detectorId);
            }}
          />
        </Stack>
        <Stack gap="xs" style={{ flex: 1 }}>
          <Text size="xs" c="dimmed" fw={600}>
            Detectors loaded: {detectorLegend.length}
          </Text>
          {visibleLegend.map((item, i) => (
            <LegendItem
              key={item.sliceKey}
              {...item}
              striped={i % 2 === 1}
              active={activeSliceKey === item.sliceKey}
              onHoverStart={() => setHoveredSliceKey(item.sliceKey)}
              onHoverEnd={() => setHoveredSliceKey((prev) => (prev === item.sliceKey ? null : prev))}
              onClick={() => copyDetectorId(item.detectorId)}
            />
          ))}
          {detectorLegend.length > MAX_VISIBLE_LEGEND_ITEMS && (
            <UnstyledButton
              onClick={() => setShowAllLegendItems((v) => !v)}
              style={{ color: "#165a8a", fontSize: "0.85em", textAlign: "left" }}
            >
              {showAllLegendItems ? "Show fewer detectors" : `Show all detectors (+${hiddenCount})`}
            </UnstyledButton>
          )}
          <Stack gap={2} mt={6}>
            <Text size="xs" c="dimmed" fw={600}>
              System
            </Text>
            {systemLegend.map((item) => (
              <LegendItem
                key={item.sliceKey}
                {...item}
                active={activeSliceKey === item.sliceKey}
                onHoverStart={() => setHoveredSliceKey(item.sliceKey)}
                onHoverEnd={() => setHoveredSliceKey((prev) => (prev === item.sliceKey ? null : prev))}
              />
            ))}
          </Stack>
        </Stack>
      </Group>
      {snackbarText && (
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
          <Text size="sm" c="white">
            {snackbarText}
          </Text>
        </Paper>
      )}
    </Paper>
  );
}
