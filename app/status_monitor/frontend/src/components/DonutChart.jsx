import { useRef } from "react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Sector } from "recharts";
import { Stack, Text } from "@mantine/core";
import { formatBytes, MIN_DETECTOR_SLOTS } from "./chartUtils";
import EvictionMarker from "./EvictionMarker";

export const DONUT_SIZE = 400;
export const DONUT_INNER_RADIUS = 110;
export const DONUT_OUTER_RADIUS = 170;

const ANIMATION_MS = 900;
const ACTIVE_RADIUS_SCALE = 1.08;
const ZERO_SLICE = { type: "placeholder", bytes: 0, color: "transparent", pct: 0, label: "" };

/** Renders a DonutChart tooltip for the slice currently under the cursor. */
function SliceTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const { payload: slice, value } = payload[0];
  return (
    <div className="donut-tooltip">
      <Text className="donut-tooltip-line" fw={600}>{slice.label}</Text>
      <Text className="donut-tooltip-line">
        {slice.resourceLabel || "VRAM"}: {formatBytes(value)} ({slice.pct.toFixed(1)}%)
      </Text>
      {slice.type === "detector" && slice.detectorId && (
        <Text className="donut-tooltip-line">{slice.detectorId}</Text>
      )}
    </div>
  );
}

/** Sector with slightly enlarged outer radius; used to emphasise the hovered slice. */
function ActiveSector(props) {
  return <Sector {...props} outerRadius={(props.outerRadius ?? DONUT_OUTER_RADIUS) * ACTIVE_RADIUS_SCALE} />;
}

/** Arranges slices into a fixed-length array of detector slots followed by the
 * three summary slices (loading / other / free).
 *
 * The data array length must stay stable between consecutive renders, otherwise
 * recharts' animation-by-array-index produces visible artifacts. We achieve this
 * by remembering every detector id we've ever rendered in `seenKeysRef` and
 * padding the array with zero-byte placeholders. When a detector disappears its
 * slot lingers at zero bytes; when a new detector appears it's appended to a
 * free slot. The array grows if needed, but never shrinks for the lifetime of
 * the component.
 */
function arrangeSlices(slices, seenKeysRef) {
  const sliceMap = new Map(slices.map((s) => [s.sliceKey, s]));
  const summarySlices = slices.filter((s) => s.type !== "detector");

  for (const s of slices) {
    if (s.type === "detector" && !seenKeysRef.current.includes(s.sliceKey)) {
      seenKeysRef.current.push(s.sliceKey);
    }
  }

  const seenKeys = seenKeysRef.current;
  const slotCount = Math.max(MIN_DETECTOR_SLOTS, seenKeys.length);
  const detectorSlots = Array.from({ length: slotCount }, (_, i) => {
    if (i >= seenKeys.length) return { ...ZERO_SLICE, sliceKey: `__pad_${i}` };
    return sliceMap.get(seenKeys[i]) || { ...ZERO_SLICE, sliceKey: seenKeys[i] };
  });

  return [...detectorSlots, ...summarySlices];
}

/** Interactive donut chart with per-slice hover, click, and smooth animation
 * across data updates.
 *
 * `slices` must include the three summary entries (loading / other / free)
 * produced by `buildSlices`. The optional `evictionThresholdPct` renders a
 * warning tick on the ring for RAM-style charts.
 */
export default function DonutChart({
  slices,
  centerText,
  activeSliceKey,
  onSliceHover,
  onSliceClick,
  evictionThresholdPct,
}) {
  const seenKeysRef = useRef([]);
  const arranged = arrangeSlices(slices, seenKeysRef);
  const data = arranged.map((s) => ({ ...s, name: s.label, value: s.bytes, fill: s.color }));

  const renderSector = (props) =>
    props?.payload?.sliceKey === activeSliceKey ? <ActiveSector {...props} /> : <Sector {...props} />;

  const totalBytes = slices.reduce((sum, s) => sum + (s.bytes || 0), 0);
  const usedBytes = slices
    .filter((s) => s.sliceKey !== "summary:free")
    .reduce((sum, s) => sum + (s.bytes || 0), 0);
  const usedPct = totalBytes > 0 ? (usedBytes / totalBytes) * 100 : 0;

  return (
    <div style={{ position: "relative", width: DONUT_SIZE, height: DONUT_SIZE, flexShrink: 0 }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            cx="50%"
            cy="50%"
            innerRadius={DONUT_INNER_RADIUS}
            outerRadius={DONUT_OUTER_RADIUS}
            startAngle={90}
            endAngle={-270}
            paddingAngle={0}
            strokeWidth={0}
            isAnimationActive
            animationDuration={ANIMATION_MS}
            animationEasing="ease-in-out"
            shape={renderSector}
            onMouseEnter={(_, index) => onSliceHover?.(data[index]?.sliceKey ?? null)}
            onMouseLeave={() => onSliceHover?.(null)}
            onClick={(_, index) => onSliceClick?.(data[index] ?? null)}
          >
            {data.map((entry, i) => (
              // Index keys are intentional: recharts animates by array position,
              // so reusing the same cell across renders keeps animation continuous.
              <Cell
                key={i}
                fill={entry.fill}
                stroke={entry.value > 0 ? "#fff" : "none"}
                strokeWidth={entry.value > 0 ? 1 : 0}
              />
            ))}
          </Pie>
          <Tooltip content={<SliceTooltip />} isAnimationActive={false} />
        </PieChart>
      </ResponsiveContainer>

      {evictionThresholdPct != null && (
        <EvictionMarker
          pct={evictionThresholdPct}
          exceeded={usedPct >= evictionThresholdPct}
          size={DONUT_SIZE}
          innerRadius={DONUT_INNER_RADIUS}
          outerRadius={DONUT_OUTER_RADIUS}
        />
      )}

      <Stack
        gap={0}
        align="center"
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          pointerEvents: "none",
        }}
      >
        <Text fw={500} size="xl">{centerText}</Text>
        <Text size="xs" c="gray.8">used</Text>
      </Stack>
    </div>
  );
}
