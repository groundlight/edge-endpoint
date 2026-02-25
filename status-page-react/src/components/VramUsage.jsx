import { Paper, Text, Group, Stack } from "@mantine/core";
import DonutChart from "./DonutChart";

const COLORS = [
  "#4A90D9", "#D94A6B", "#D9A94A", "#4AD9A9", "#9B59B6",
  "#E67E22", "#1ABC9C", "#E74C3C", "#3498DB", "#2ECC71",
];
const FREE_COLOR = "#E0E0E0";
const LOADING_COLOR = "#555555";
const OTHER_COLOR = "#B0B0B0";

function formatBytes(bytes) {
  if (bytes == null) return "--";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

function LegendItem({ color, label, value }) {
  return (
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
    </Group>
  );
}

function GpuCard({ gpu, detectors, loadingVramBytes, detNameMap }) {
  const totalBytes = gpu.total_bytes;
  const slices = [];
  const legend = [];
  let accountedBytes = 0;

  detectors.forEach((det, i) => {
    const color = COLORS[i % COLORS.length];
    const bytes = det.total_vram_bytes || 0;
    accountedBytes += bytes;
    slices.push({ bytes, color, label: detNameMap[det.detector_id] || det.detector_id });
    legend.push({ color, label: detNameMap[det.detector_id] || det.detector_id, value: formatBytes(bytes) });
  });

  if (loadingVramBytes > 0) {
    accountedBytes += loadingVramBytes;
    slices.push({ bytes: loadingVramBytes, color: LOADING_COLOR, label: "Loading Detector Models" });
    legend.push({ color: LOADING_COLOR, label: "Loading Detector Models", value: formatBytes(loadingVramBytes) });
  }

  const otherBytes = Math.max(0, gpu.used_bytes - accountedBytes);
  if (otherBytes > 0) {
    slices.push({ bytes: otherBytes, color: OTHER_COLOR, label: "Other" });
    legend.push({ color: OTHER_COLOR, label: "Other", value: formatBytes(otherBytes) });
  }

  const freeBytes = Math.max(0, totalBytes - gpu.used_bytes);
  slices.push({ bytes: freeBytes, color: FREE_COLOR, label: "Free" });
  legend.push({ color: FREE_COLOR, label: "Free", value: formatBytes(freeBytes) });

  const usedPct = `${((gpu.used_bytes / totalBytes) * 100).toFixed(0)}%`;

  return (
    <Paper shadow="xs" p="lg" radius="sm">
      <Text fw={500} mb="md">
        GPU {gpu.index}: {gpu.name} ({formatBytes(gpu.total_bytes)})
      </Text>
      <Group gap="xl" align="center">
        <DonutChart slices={slices} centerText={usedPct} />
        <Stack gap="xs">
          {legend.map((item, i) => (
            <LegendItem key={i} {...item} />
          ))}
        </Stack>
      </Group>
    </Paper>
  );
}

export default function VramUsage({ gpuData, detectorDetails }) {
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

  const gpus = gpuData.gpus || [];
  const detectors = gpuData.detectors || [];

  if (gpus.length === 0) {
    return (
      <Paper shadow="xs" p="md" radius="sm">
        <Text c="dimmed" fs="italic">
          No GPU data available.
        </Text>
      </Paper>
    );
  }

  const detNameMap = {};
  if (detectorDetails) {
    for (const [id, info] of Object.entries(detectorDetails)) {
      detNameMap[id] = info.detector_name || id;
    }
  }

  return (
    <Stack gap="sm">
      {gpus.map((gpu, i) => (
        <GpuCard
          key={gpu.uuid || i}
          gpu={gpu}
          detectors={detectors}
          loadingVramBytes={gpuData.loading_vram_bytes || 0}
          detNameMap={detNameMap}
        />
      ))}
    </Stack>
  );
}
