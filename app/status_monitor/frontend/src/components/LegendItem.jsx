import { Group, Text, Tooltip } from "@mantine/core";

const CELL_VALUE_STYLE = { whiteSpace: "nowrap", minWidth: 64, textAlign: "right" };
const CELL_PCT_STYLE = { whiteSpace: "nowrap", minWidth: 48, textAlign: "right" };

/** A single row in the shared legend, with optional VRAM and always-on RAM columns.
 *
 * Rendering and hover state are driven entirely by the parent; this component
 * is pure. Set `onClick` to make the row act as a button (e.g. for copying
 * a detector id). Set `helpText` to show a tooltip when the row is hovered.
 */
export default function LegendItem({
  color,
  label,
  vramValue,
  vramPct,
  ramValue,
  ramPct,
  hasVram,
  helpText,
  striped = false,
  active = false,
  onHoverStart,
  onHoverEnd,
  onClick,
}) {
  const clickable = Boolean(onClick);
  const background = active ? "#e9f2ff" : striped ? "#f7f8fa" : "transparent";
  const border = active ? "1px solid #7aa7e0" : "1px solid transparent";

  const row = (
    <div
      style={{
        padding: "3px 6px",
        borderRadius: 4,
        backgroundColor: background,
        border,
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
            <Text size="sm" fw={500} style={CELL_VALUE_STYLE}>{vramValue}</Text>
            <Text size="sm" c="gray.8" style={CELL_PCT_STYLE}>{vramPct}</Text>
          </>
        )}
        <Text size="sm" fw={500} style={CELL_VALUE_STYLE}>{ramValue}</Text>
        <Text size="sm" c="gray.8" style={CELL_PCT_STYLE}>{ramPct}</Text>
      </Group>
    </div>
  );

  if (!helpText) return row;
  return (
    <Tooltip label={helpText} multiline w={260} openDelay={300} position="top" withArrow>
      {row}
    </Tooltip>
  );
}
