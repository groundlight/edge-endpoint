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

/** Renders an interactive donut chart with hover callbacks. */
export default function DonutChart({
  slices,
  centerText,
  activeSliceKey,
  onSliceHover,
  onSliceClick,
}) {
  const data = slices.map((s) => ({ ...s, name: s.label, value: s.bytes, fill: s.color }));

  const renderSlice = (props) => {
    const isActive = props?.payload?.sliceKey === activeSliceKey;
    if (isActive) {
      return <ActiveSlice {...props} />;
    }
    return <Sector {...props} />;
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
            paddingAngle={1}
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
              <Cell key={entry.sliceKey} fill={entry.fill} />
            ))}
          </Pie>
          <Tooltip content={<CustomTooltip />} isAnimationActive={false} />
        </PieChart>
      </ResponsiveContainer>
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
        <Text size="xs" c="dimmed">
          used
        </Text>
      </Stack>
    </div>
  );
}
