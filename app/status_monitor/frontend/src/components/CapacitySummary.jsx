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
  const getTotal = (gpu) => gpu?.total_vram_bytes ?? gpu?.total_bytes ?? 0;
  const getUsed = (gpu) => gpu?.used_vram_bytes ?? gpu?.used_bytes ?? 0;

  if (gpus.length === 0) {
    return <InlineSummary usedBytes={usedBytes} totalBytes={totalBytes} />;
  }

  if (gpus.length === 1) {
    const gpu = gpus[0];
    return (
      <Text size="sm" fw={500}>
        {gpu.name} ({formatBytes(getUsed(gpu))} / {formatBytes(getTotal(gpu))},{" "}
        {formatPctInt(getUsed(gpu), getTotal(gpu))})
      </Text>
    );
  }

  const totalGpuBytes = gpus.reduce((sum, gpu) => sum + getTotal(gpu), 0);
  const usedGpuBytes = gpus.reduce((sum, gpu) => sum + getUsed(gpu), 0);
  return (
    <Stack gap={2}>
      <InlineSummary usedBytes={usedGpuBytes} totalBytes={totalGpuBytes} />
      {gpus.map((gpu, i) => (
        <Text key={`${gpu.name}-${i}`} size="xs" c="gray.8">
          GPU {gpu.index ?? i}: {gpu.name} ({formatBytes(getUsed(gpu))} /{" "}
          {formatBytes(getTotal(gpu))})
        </Text>
      ))}
    </Stack>
  );
}

/** Renders a system-RAM capacity summary above the RAM donut. */
export function RamCapacitySummary({ totalBytes, usedBytes }) {
  return <InlineSummary usedBytes={usedBytes} totalBytes={totalBytes} />;
}
