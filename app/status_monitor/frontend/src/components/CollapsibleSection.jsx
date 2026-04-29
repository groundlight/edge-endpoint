import { useState, useId } from "react";
import { Stack, Group, Text, UnstyledButton, Collapse } from "@mantine/core";
import { SECTION_TITLE_STYLE } from "../sharedStyles";

// Standard wrapper for every top-level section on the status page. Renders a
// click-to-toggle title row (chevron + title text) above a Mantine Collapse
// containing the section body. The chevron rotates 90 degrees as visual
// feedback for the open/closed state. Per-instance state, so each section
// remembers its own open/closed independently across the polling refresh.
//
// Note: Mantine's <Collapse> hides children but does NOT unmount them, so
// any expensive work in the body (e.g. CodeSection's serializer useMemo)
// continues to run on every poll while the section is collapsed. Trivial
// for our payloads; revisit if a future child becomes truly expensive.
//
//   title       - heading text shown next to the chevron.
//   defaultOpen - initial open state. Defaults to true; set false for
//                 noisy / rarely-interesting sections. Only used on first
//                 mount; later changes to the prop are ignored.
//   children    - section body. Rendered inside the Collapse, with the
//                 standard "xs" gap between title row and body.
function ChevronIcon({ open }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{
        transform: open ? "rotate(90deg)" : "rotate(0deg)",
        transition: "transform 150ms ease",
        flexShrink: 0,
        color: "#666",
      }}
    >
      <polyline points="9 6 15 12 9 18" />
    </svg>
  );
}

export default function CollapsibleSection({ title, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  return (
    <Stack gap="xs">
      <UnstyledButton
        className="collapsible-section-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={bodyId}
      >
        <Group gap="xs" wrap="nowrap">
          <ChevronIcon open={open} />
          <Text style={SECTION_TITLE_STYLE}>{title}</Text>
        </Group>
      </UnstyledButton>
      <Collapse in={open} id={bodyId}>
        {children}
      </Collapse>
    </Stack>
  );
}
