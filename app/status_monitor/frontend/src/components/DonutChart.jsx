import { useRef, useState } from "react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Sector } from "recharts";
import { Text, Stack } from "@mantine/core";

export const DONUT_SIZE = 400;
export const DONUT_INNER_RADIUS = 110;
export const DONUT_OUTER_RADIUS = 170;

/** Formats bytes as GB/MB for tooltip display. */
function formatBytes(bytes) {
  if (bytes == null) return "--";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

/** Renders the hover tooltip content for a pie slice. */
function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const { payload: item, value } = payload[0];
  const resourceLabel = item.resourceLabel || "VRAM";
  return (
    <div className="donut-tooltip">
      <Text className="donut-tooltip-line" fw={600}>
        {item.label}
      </Text>
      <Text className="donut-tooltip-line">
        {resourceLabel}: {formatBytes(value)} ({item.pct.toFixed(1)}%)
      </Text>
      {item.type === "detector" && item.detectorId && (
        <Text className="donut-tooltip-line">{item.detectorId}</Text>
      )}
    </div>
  );
}

/** Renders an enlarged sector for the active slice. */
function ActiveSlice(props) {
  return (
    <Sector
      {...props}
      outerRadius={(props.outerRadius ?? DONUT_OUTER_RADIUS) * 1.08}
    />
  );
}

/** Renders a tick mark on the donut ring at the eviction threshold angle. */
function EvictionThresholdMarker({ pct, exceeded }) {
  const color = exceeded ? "#d32f2f" : "#333";
  const [hovered, setHovered] = useState(false);
  const cx = DONUT_SIZE / 2;
  const cy = DONUT_SIZE / 2;
  const angleDeg = 90 - (pct / 100) * 360;
  const angleRad = (angleDeg * Math.PI) / 180;
  const innerR = DONUT_INNER_RADIUS - 6;
  const outerR = DONUT_OUTER_RADIUS + 6;
  const x1 = cx + innerR * Math.cos(angleRad);
  const y1 = cy - innerR * Math.sin(angleRad);
  const x2 = cx + outerR * Math.cos(angleRad);
  const y2 = cy - outerR * Math.sin(angleRad);

  const labelR = innerR - 14;
  const labelX = cx + labelR * Math.cos(angleRad);
  const labelY = cy - labelR * Math.sin(angleRad);

  const midR = (innerR + outerR) / 2;
  const tooltipX = cx + midR * Math.cos(angleRad);
  const tooltipY = cy - midR * Math.sin(angleRad);

  return (
    <>
      <svg
        width={DONUT_SIZE}
        height={DONUT_SIZE}
        style={{ position: "absolute", top: 0, left: 0, pointerEvents: "none" }}
      >
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={2.5} strokeDasharray="4 2" />
        {/* Wider invisible hit area on the tick mark */}
        <line
          x1={x1} y1={y1} x2={x2} y2={y2}
          stroke="transparent" strokeWidth={16}
          style={{ pointerEvents: "auto", cursor: "default" }}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
        />
        <text
          x={labelX} y={labelY}
          textAnchor="middle" dominantBaseline="central"
          fill={color} fontSize={14} fontWeight={700}
          style={{ pointerEvents: "auto", cursor: "default" }}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
        >
          {pct}%
        </text>
      </svg>
      {hovered && (
        <div
          className="donut-tooltip"
          style={{
            position: "absolute",
            left: tooltipX,
            top: tooltipY,
            transform: "translate(-50%, -120%)",
            pointerEvents: "none",
            whiteSpace: "nowrap",
            zIndex: 10,
          }}
        >
          <Text className="donut-tooltip-line" fw={600}>
            Pod eviction threshold
          </Text>
          <Text className="donut-tooltip-line">
            Kubernetes will evict pods when RAM usage exceeds {pct}%.
          </Text>
        </div>
      )}
    </>
  );
}

/** Renders an interactive donut chart with hover callbacks. */
export default function DonutChart({
  slices,
  centerText,
  activeSliceKey,
  onSliceHover,
  onSliceClick,
  evictionThresholdPct,
}) {
  const MAX_DETECTOR_SLOTS = 30;
  const ZERO_SLICE = { type: "placeholder", bytes: 0, color: "transparent", pct: 0, label: "" };

  const seenDetectorKeysRef = useRef([]);
  const seenKeys = seenDetectorKeysRef.current;


  const sliceMap = new Map(slices.map((s) => [s.sliceKey, s]));
  const summarySlices = slices.filter((s) => s.type !== "detector");

  for (const s of slices) {
    if (s.type === "detector" && !seenKeys.includes(s.sliceKey)) {
      seenKeys.push(s.sliceKey);
    }
  }

  const detectorSlices = Array.from({ length: MAX_DETECTOR_SLOTS }, (_, i) =>
    i < seenKeys.length
      ? sliceMap.get(seenKeys[i]) || { ...ZERO_SLICE, sliceKey: seenKeys[i] }
      : { ...ZERO_SLICE, sliceKey: `__pad_${i}` }
  );

  const data = [...detectorSlices, ...summarySlices].map((s) => ({ ...s, name: s.label, value: s.bytes, fill: s.color }));

  const renderSlice = (props) => {
    const isActive = props?.payload?.sliceKey === activeSliceKey;
    return isActive ? <ActiveSlice {...props} /> : <Sector {...props} />;
  };

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
            animationDuration={900}
            animationEasing="ease-in-out"
            shape={renderSlice}
            onMouseEnter={(_, index) => onSliceHover?.(data[index]?.sliceKey ?? null)}
            onMouseLeave={() => onSliceHover?.(null)}
            onClick={(_, index) => onSliceClick?.(data[index] ?? null)}
          >
            {data.map((entry, i) => (
              <Cell
                key={i}
                fill={entry.fill}
                stroke={entry.value > 0 ? "#fff" : "none"}
                strokeWidth={entry.value > 0 ? 1 : 0}
              />
            ))}
          </Pie>
          <Tooltip content={<CustomTooltip />} isAnimationActive={false} />
        </PieChart>
      </ResponsiveContainer>
      {evictionThresholdPct != null && (() => {
        const totalBytes = slices.reduce((sum, s) => sum + (s.bytes || 0), 0);
        const usedBytes = slices.filter((s) => s.sliceKey !== "summary:free").reduce((sum, s) => sum + (s.bytes || 0), 0);
        const usedPct = totalBytes > 0 ? (usedBytes / totalBytes) * 100 : 0;
        return <EvictionThresholdMarker pct={evictionThresholdPct} exceeded={usedPct >= evictionThresholdPct} />;
      })()}
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
        <Text fw={500} size="xl">
          {centerText}
        </Text>
        <Text size="xs" c="gray.8">
          used
        </Text>
      </Stack>
    </div>
  );
}
