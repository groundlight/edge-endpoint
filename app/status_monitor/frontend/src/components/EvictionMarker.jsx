import { useState } from "react";
import { Text } from "@mantine/core";

/** Renders a dashed tick on a donut's ring at the given percentage angle,
 * with a hover tooltip explaining the Kubernetes pod eviction threshold.
 *
 * The marker is drawn as a sibling SVG overlaid on top of the donut; it is
 * positioned relative to the parent container (which must be
 * `position: relative`). `size` and the ring radii are passed in so this
 * component stays decoupled from DonutChart's layout constants.
 */
export default function EvictionMarker({ pct, exceeded, size, innerRadius, outerRadius }) {
  const [hovered, setHovered] = useState(false);
  const color = exceeded ? "#d32f2f" : "#333";
  const cx = size / 2;
  const cy = size / 2;

  const angleRad = ((90 - (pct / 100) * 360) * Math.PI) / 180;
  const cos = Math.cos(angleRad);
  const sin = Math.sin(angleRad);

  const innerR = innerRadius - 6;
  const outerR = outerRadius + 6;
  const x1 = cx + innerR * cos;
  const y1 = cy - innerR * sin;
  const x2 = cx + outerR * cos;
  const y2 = cy - outerR * sin;

  const labelR = innerR - 14;
  const labelX = cx + labelR * cos;
  const labelY = cy - labelR * sin;

  const midR = (innerR + outerR) / 2;
  const tooltipX = cx + midR * cos;
  const tooltipY = cy - midR * sin;

  const hoverProps = {
    onMouseEnter: () => setHovered(true),
    onMouseLeave: () => setHovered(false),
    style: { pointerEvents: "auto", cursor: "default" },
  };

  return (
    <>
      <svg
        width={size}
        height={size}
        style={{ position: "absolute", top: 0, left: 0, pointerEvents: "none" }}
      >
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={2.5} strokeDasharray="4 2" />
        {/* Wider transparent hit-area on top of the tick for easier hovering. */}
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="transparent" strokeWidth={16} {...hoverProps} />
        <text
          x={labelX}
          y={labelY}
          textAnchor="middle"
          dominantBaseline="central"
          fill={color}
          fontSize={14}
          fontWeight={700}
          {...hoverProps}
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
