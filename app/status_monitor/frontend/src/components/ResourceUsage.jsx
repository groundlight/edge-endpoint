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

function formatBytes(bytes) {
  if (bytes == null) return "--";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

function formatPct(bytes, totalBytes) {
  if (!totalBytes) return "0.0%";
  return `${((bytes / totalBytes) * 100).toFixed(1)}%`;
}

function formatPctInt(bytes, totalBytes) {
  if (!totalBytes) return "0%";
  return `${Math.round((bytes / totalBytes) * 100)}%`;
}

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
        {gpu.name} ({formatBytes(gpuUsed)} / {formatBytes(gpuTotal)}, {formatPctInt(gpuUsed, gpuTotal)})
      </Text>
    );
  }
  if (gpus.length > 1) {
    const totalGpuBytes = gpus.reduce((sum, gpu) => sum + getTotal(gpu), 0);
    const usedGpuBytes = gpus.reduce((sum, gpu) => sum + getUsed(gpu), 0);
    return (
      <Stack gap={2}>
        <Text size="sm" fw={500}>
          {formatBytes(usedGpuBytes)} / {formatBytes(totalGpuBytes)}, {formatPctInt(usedGpuBytes, totalGpuBytes)}
        </Text>
        {gpus.map((gpu, i) => (
          <Text key={`${gpu.name}-${i}`} size="xs" c="gray.8">
            GPU {gpu.index ?? i}: {gpu.name} ({formatBytes(getUsed(gpu))} / {formatBytes(getTotal(gpu))})
          </Text>
        ))}
      </Stack>
    );
  }
  return (
    <Text size="sm" fw={500}>
      {formatBytes(usedBytes)} / {formatBytes(totalBytes)}, {formatPctInt(usedBytes, totalBytes)}
    </Text>
  );
}

function RamCapacitySummary({ totalBytes, usedBytes }) {
  return (
    <Text size="sm" fw={500}>
      {formatBytes(usedBytes)} / {formatBytes(totalBytes)}, {formatPctInt(usedBytes, totalBytes)}
    </Text>
  );
}

/** Builds donut slices and computes summary values for one resource type. */
function buildSlices({ detectors, detNameMap, totalBytes, usedBytes, loadingBytes, colorMap, vramKey, resourceLabel }) {
  const slices = [];
  let accountedBytes = 0;

  detectors.forEach((det) => {
    const color = colorMap[det.detector_id] || "#999";
    const label = detNameMap[det.detector_id] || det.detector_id;
    const bytes = det[vramKey] || 0;
    accountedBytes += bytes;
    slices.push({
      sliceKey: `det:${det.detector_id}`,
      type: "detector",
      detectorId: det.detector_id,
      label,
      bytes,
      color,
      pct: totalBytes ? (bytes / totalBytes) * 100 : 0,
      resourceLabel,
    });
  });

  accountedBytes += loadingBytes;
  slices.push({
    sliceKey: "summary:loading",
    type: "summary",
    label: "Loading Detector Models",
    bytes: loadingBytes,
    color: LOADING_COLOR,
    pct: totalBytes ? (loadingBytes / totalBytes) * 100 : 0,
    resourceLabel,
  });

  const otherBytes = Math.max(0, usedBytes - accountedBytes);
  slices.push({
    sliceKey: "summary:other",
    type: "summary",
    label: "Other",
    bytes: otherBytes,
    color: OTHER_COLOR,
    pct: totalBytes ? (otherBytes / totalBytes) * 100 : 0,
    resourceLabel,
  });

  const freeBytes = Math.max(0, totalBytes - usedBytes);
  slices.push({
    sliceKey: "summary:free",
    type: "summary",
    label: "Free",
    bytes: freeBytes,
    color: FREE_COLOR,
    pct: totalBytes ? (freeBytes / totalBytes) * 100 : 0,
    resourceLabel,
  });

  return { slices, otherBytes, freeBytes };
}

/** Renders one row in the shared legend with VRAM and RAM columns. */
function LegendItem({
  color,
  label,
  vramValue,
  vramPct,
  ramValue,
  ramPct,
  hasVram,
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
        <Text size="sm" style={{ flex: 1, minWidth: 0 }}>
          {label}
        </Text>
        {hasVram && (
          <>
            <Text size="sm" fw={500} style={{ whiteSpace: "nowrap", minWidth: 64, textAlign: "right" }}>
              {vramValue}
            </Text>
            <Text size="sm" c="gray.8" style={{ whiteSpace: "nowrap", minWidth: 48, textAlign: "right" }}>
              {vramPct}
            </Text>
          </>
        )}
        <Text size="sm" fw={500} style={{ whiteSpace: "nowrap", minWidth: 64, textAlign: "right" }}>
          {ramValue}
        </Text>
        <Text size="sm" c="gray.8" style={{ whiteSpace: "nowrap", minWidth: 48, textAlign: "right" }}>
          {ramPct}
        </Text>
      </Group>
    </div>
  );
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

export default function ResourceUsage({ resourceData, detectorDetails, loading }) {
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

  if (loading && !resourceData) return <ResourceUsageSkeleton />;
  if (!resourceData) return null;

  if (resourceData.error) {
    return (
      <Paper shadow="xs" p="md" radius="sm">
        <Text c="gray.8" fs="italic">
          {resourceData.error}
        </Text>
      </Paper>
    );
  }

  const totalVram = resourceData.total_vram_bytes || 0;
  const usedVram = resourceData.used_vram_bytes || 0;
  const totalRam = resourceData.total_ram_bytes || 0;
  const usedRam = resourceData.used_ram_bytes || 0;
  const hasVram = totalVram > 0;
  const hasRam = totalRam > 0;

  if (!hasVram && !hasRam) {
    return (
      <Paper shadow="xs" p="md" radius="sm">
        <Text c="gray.8" fs="italic">
          No resource data available.
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

  const detectors = (resourceData.detectors || []).slice().sort((a, b) => {
    const timeCmp = (detDeployTime[a.detector_id] || "").localeCompare(detDeployTime[b.detector_id] || "");
    return timeCmp !== 0 ? timeCmp : a.detector_id.localeCompare(b.detector_id);
  });

  // Assign stable colors to detectors
  const colorMap = {};
  detectors.forEach((det, i) => {
    colorMap[det.detector_id] = COLORS[i % COLORS.length];
  });

  const loadingVram = resourceData.loading_vram_bytes || 0;
  const loadingRam = resourceData.loading_ram_bytes || 0;

  const vramResult = hasVram
    ? buildSlices({
        detectors, detNameMap, totalBytes: totalVram, usedBytes: usedVram,
        loadingBytes: loadingVram, colorMap, vramKey: "total_vram_bytes", resourceLabel: "VRAM",
      })
    : null;

  const ramResult = hasRam
    ? buildSlices({
        detectors, detNameMap, totalBytes: totalRam, usedBytes: usedRam,
        loadingBytes: loadingRam, colorMap, vramKey: "total_ram_bytes", resourceLabel: "RAM",
      })
    : null;

  const vramPct = hasVram ? `${((usedVram / totalVram) * 100).toFixed(0)}%` : "0%";
  const ramPct = hasRam ? `${((usedRam / totalRam) * 100).toFixed(0)}%` : "0%";

  // Build shared legend entries
  const detectorLegend = detectors.map((det) => ({
    sliceKey: `det:${det.detector_id}`,
    detectorId: det.detector_id,
    color: colorMap[det.detector_id],
    label: detNameMap[det.detector_id] || det.detector_id,
    vramValue: formatBytes(det.total_vram_bytes || 0),
    vramPct: formatPct(det.total_vram_bytes || 0, totalVram),
    ramValue: formatBytes(det.total_ram_bytes || 0),
    ramPct: formatPct(det.total_ram_bytes || 0, totalRam),
  }));

  const hiddenCount = Math.max(0, detectorLegend.length - MAX_VISIBLE_LEGEND_ITEMS);
  const visibleLegend = showAllLegendItems
    ? detectorLegend
    : detectorLegend.slice(0, MAX_VISIBLE_LEGEND_ITEMS);

  const systemLegend = [
    {
      sliceKey: "summary:loading",
      color: LOADING_COLOR,
      label: "Loading Detector Models",
      vramValue: formatBytes(loadingVram),
      vramPct: formatPct(loadingVram, totalVram),
      ramValue: formatBytes(loadingRam),
      ramPct: formatPct(loadingRam, totalRam),
    },
    {
      sliceKey: "summary:other",
      color: OTHER_COLOR,
      label: "Other",
      vramValue: formatBytes(vramResult?.otherBytes ?? 0),
      vramPct: formatPct(vramResult?.otherBytes ?? 0, totalVram),
      ramValue: formatBytes(ramResult?.otherBytes ?? 0),
      ramPct: formatPct(ramResult?.otherBytes ?? 0, totalRam),
    },
    {
      sliceKey: "summary:free",
      color: FREE_COLOR,
      label: "Free",
      vramValue: formatBytes(vramResult?.freeBytes ?? 0),
      vramPct: formatPct(vramResult?.freeBytes ?? 0, totalVram),
      ramValue: formatBytes(ramResult?.freeBytes ?? 0),
      ramPct: formatPct(ramResult?.freeBytes ?? 0, totalRam),
    },
  ];

  const onSliceHover = (key) => setHoveredSliceKey(key);
  const onSliceClick = (slice) => {
    if (slice?.type !== "detector") return;
    copyDetectorId(slice.detectorId);
  };

  return (
    <Paper shadow="xs" p="lg" radius="sm">
      <div className="resource-donuts-row">
        {hasVram && (
          <Stack gap="xs" align="center">
            <Text size="xs" fw={600} c="gray.8">VRAM</Text>
            <GpuCapacitySummary
              observedGpus={resourceData.observed_gpus}
              totalBytes={totalVram}
              usedBytes={usedVram}
            />
            <DonutChart
              slices={vramResult.slices}
              centerText={vramPct}
              activeSliceKey={hoveredSliceKey}
              onSliceHover={onSliceHover}
              onSliceClick={onSliceClick}
            />
          </Stack>
        )}
        {hasRam && (
          <Stack gap="xs" align="center">
            <Text size="xs" fw={600} c="gray.8">RAM</Text>
            <RamCapacitySummary totalBytes={totalRam} usedBytes={usedRam} />
            <DonutChart
              slices={ramResult.slices}
              centerText={ramPct}
              activeSliceKey={hoveredSliceKey}
              onSliceHover={onSliceHover}
              onSliceClick={onSliceClick}
            />
          </Stack>
        )}
      </div>

      <Stack gap="xs" mt="md">
        <div style={{ padding: "3px 6px" }}>
          <Group gap="xs" wrap="nowrap">
            <div style={{ width: 14, flexShrink: 0 }} />
            <Text size="xs" c="gray.8" fw={600} style={{ flex: 1, minWidth: 0 }}>
              Detectors loaded: {detectorLegend.length}
            </Text>
            {hasVram && (
              <>
                <Text size="xs" c="gray.8" fw={600} style={{ whiteSpace: "nowrap", minWidth: 64, textAlign: "right" }}>
                  VRAM
                </Text>
                <div style={{ minWidth: 48 }} />
              </>
            )}
            <Text size="xs" c="gray.8" fw={600} style={{ whiteSpace: "nowrap", minWidth: 64, textAlign: "right" }}>
              RAM
            </Text>
            <div style={{ minWidth: 48 }} />
          </Group>
        </div>
        {visibleLegend.map((item, i) => (
          <LegendItem
            key={item.sliceKey}
            {...item}
            hasVram={hasVram}
            striped={i % 2 === 1}
            active={hoveredSliceKey === item.sliceKey}
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
          <Text size="xs" c="gray.8" fw={600}>
            System
          </Text>
          {systemLegend.map((item) => (
            <LegendItem
              key={item.sliceKey}
              {...item}
              hasVram={hasVram}
              active={hoveredSliceKey === item.sliceKey}
              onHoverStart={() => setHoveredSliceKey(item.sliceKey)}
              onHoverEnd={() => setHoveredSliceKey((prev) => (prev === item.sliceKey ? null : prev))}
            />
          ))}
        </Stack>
      </Stack>

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
