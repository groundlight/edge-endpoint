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
    return (
      <Text size="sm" fw={500}>
        {gpu.name} ({formatBytes(gpu.used_bytes)} / {formatBytes(gpu.total_bytes)},{" "}
        {formatPctInt(gpu.used_bytes, gpu.total_bytes)})
      </Text>
    );
  }

  const totalGpuBytes = gpus.reduce((sum, gpu) => sum + (gpu.total_bytes || 0), 0);
  const usedGpuBytes = gpus.reduce((sum, gpu) => sum + (gpu.used_bytes || 0), 0);
  return (
    <Stack gap={2}>
      <InlineSummary usedBytes={usedGpuBytes} totalBytes={totalGpuBytes} />
      {gpus.map((gpu, i) => (
        <Text key={`${gpu.name}-${i}`} size="xs" c="gray.8">
          GPU {gpu.index ?? i}: {gpu.name} ({formatBytes(gpu.used_bytes)} /{" "}
          {formatBytes(gpu.total_bytes)})
        </Text>
      ))}
    </Stack>
  );
}

/** Renders a system-RAM capacity summary above the RAM donut. */
export function RamCapacitySummary({ totalBytes, usedBytes }) {
  return <InlineSummary usedBytes={usedBytes} totalBytes={totalBytes} />;
}
