import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { Text, Stack } from "@mantine/core";

function formatBytes(bytes) {
  if (bytes == null) return "--";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const { name, value, fill } = payload[0];
  return (
    <div className="donut-tooltip">
      <span className="donut-tooltip-swatch" style={{ backgroundColor: fill }} />
      <span>{name}: {formatBytes(value)}</span>
    </div>
  );
}

export default function DonutChart({ slices, centerText }) {
  const data = slices
    .filter((s) => s.bytes > 0)
    .map((s) => ({ name: s.label, value: s.bytes, fill: s.color }));

  return (
    <div style={{ position: "relative", width: 200, height: 200, flexShrink: 0 }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            cx="50%"
            cy="50%"
            innerRadius={55}
            outerRadius={85}
            paddingAngle={1}
            strokeWidth={0}
            animationDuration={600}
          >
            {data.map((entry, i) => (
              <Cell key={i} fill={entry.fill} />
            ))}
          </Pie>
          <Tooltip content={<CustomTooltip />} />
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
