import { Stack, Text } from "@mantine/core";
import { formatBytes, formatPctInt } from "./chartUtils";

/** Single-line summary of used / total bytes with percentage. */
function InlineSummary({ usedBytes, totalBytes }) {
  return (
    <Text size="sm" fw={500}>
      {formatBytes(usedBytes)} / {formatBytes(totalBytes)}, {formatPctInt(usedBytes, totalBytes)}
    </Text>
  );
}

/** Renders a GPU capacity summary above the VRAM donut.
 *
 * Shows the GPU model when a single GPU is present, a total + per-GPU
 * breakdown when multiple GPUs are observed, or just an aggregate line if
 * no GPUs were identified by name.
 */
export function GpuCapacitySummary({ observedGpus, totalBytes, usedBytes }) {
  const gpus = (observedGpus || []).filter((g) => g?.name);

  if (gpus.length === 0) {
    return <InlineSummary usedBytes={usedBytes} totalBytes={totalBytes} />;
  }

  if (gpus.length === 1) {
    const gpu = gpus[0];
    const vram = gpu.vram_bytes || {};
    return (
      <Text size="sm" fw={500}>
        {gpu.name} ({formatBytes(vram.used)} / {formatBytes(vram.total)},{" "}
        {formatPctInt(vram.used, vram.total)})
      </Text>
    );
  }

  const totalGpuBytes = gpus.reduce((sum, gpu) => sum + (gpu.vram_bytes?.total || 0), 0);
  const usedGpuBytes = gpus.reduce((sum, gpu) => sum + (gpu.vram_bytes?.used || 0), 0);
  return (
    <Stack gap={2}>
      <InlineSummary usedBytes={usedGpuBytes} totalBytes={totalGpuBytes} />
      {gpus.map((gpu, i) => (
        <Text key={`${gpu.name}-${i}`} size="xs" c="gray.8">
          GPU {gpu.index ?? i}: {gpu.name} ({formatBytes(gpu.vram_bytes?.used)} /{" "}
          {formatBytes(gpu.vram_bytes?.total)})
        </Text>
      ))}
    </Stack>
  );
}

/** Renders a system-RAM capacity summary above the RAM donut. */
export function RamCapacitySummary({ totalBytes, usedBytes }) {
  return <InlineSummary usedBytes={usedBytes} totalBytes={totalBytes} />;
}
