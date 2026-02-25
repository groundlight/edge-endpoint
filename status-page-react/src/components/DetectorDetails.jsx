import { useState, useMemo } from "react";
import {
  Table,
  Badge,
  Tooltip,
  Text,
  Anchor,
  Paper,
  Skeleton,
  Stack,
  UnstyledButton,
  Group,
} from "@mantine/core";

const STATUS_CONFIG = {
  ready: { label: "Ready", color: "green" },
  updating: { label: "Updating", color: "blue" },
  update_failed: { label: "Update Failed", color: "orange" },
  initializing: { label: "Initializing", color: "yellow" },
  error: { label: "Error", color: "red" },
};

const STATUS_TOOLTIP =
  "Ready: Model is loaded and serving inference requests.\n" +
  "Updating: New model version deploying. Previous version still serving.\n" +
  "Update Failed: New version failed to start. Previous version still serving.\n" +
  "Initializing: Model is loading for the first time. Not yet available.\n" +
  "Error: Model failed to start.";

function formatTimestamp(isoString) {
  if (!isoString) return null;
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return null;

  const formatter = new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
    timeZoneName: "short",
  });

  const parts = formatter.formatToParts(date);
  const get = (type) => parts.find((p) => p.type === type)?.value || "";
  const dateStr = `${get("month")}/${get("day")}/${get("year")}`;
  const timeStr =
    `${get("hour")}:${get("minute")}:${get("second")} ${get("dayPeriod")} ${get("timeZoneName")}`.trim();

  const diffSec = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  let relative;
  if (diffSec < 60) {
    relative = `${diffSec} second${diffSec === 1 ? "" : "s"} ago`;
  } else if (diffSec < 3600) {
    const m = Math.floor(diffSec / 60);
    relative = `${m} minute${m === 1 ? "" : "s"} ago`;
  } else if (diffSec < 86400) {
    const h = Math.floor(diffSec / 3600);
    relative = `${h} hour${h === 1 ? "" : "s"} ago`;
  } else {
    const d = Math.floor(diffSec / 86400);
    relative = `${d} day${d === 1 ? "" : "s"} ago`;
  }

  return { date: dateStr, time: timeStr, relative };
}

function StatusBadge({ status, statusDetail }) {
  const cfg = STATUS_CONFIG[status] || { label: status || "Unknown", color: "gray" };
  return (
    <Stack gap={4} align="center">
      <Badge
        variant="light"
        color={cfg.color}
        size="lg"
        style={{ minWidth: "fit-content", whiteSpace: "nowrap" }}
      >
        {cfg.label}
      </Badge>
      {(status === "error" || status === "update_failed") && statusDetail && (
        <Text size="xs" c="dimmed">
          {statusDetail}
        </Text>
      )}
    </Stack>
  );
}

function EdgeConfigTable({ config }) {
  if (!config || Object.keys(config).length === 0) return <Text c="dimmed">--</Text>;
  return (
    <table className="edge-config-table">
      <tbody>
        {Object.entries(config).map(([k, v]) => (
          <tr key={k}>
            <td>{k}</td>
            <td>{String(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TimestampCell({ isoString }) {
  const ts = formatTimestamp(isoString);
  if (!ts) return <Text c="dimmed">--</Text>;
  return (
    <Stack gap={0}>
      <Text size="sm">{ts.date}</Text>
      <Text size="sm">{ts.time}</Text>
      <Text size="xs" c="dimmed">
        ({ts.relative})
      </Text>
    </Stack>
  );
}

function SortIcon({ direction }) {
  if (!direction) return <span className="sort-icon">&#8693;</span>;
  return (
    <span className="sort-icon">
      {direction === "asc" ? "\u25B2" : "\u25BC"}
    </span>
  );
}

function getTimestamp(info) {
  if (!info?.last_updated_time) return 0;
  const t = new Date(info.last_updated_time).getTime();
  return Number.isNaN(t) ? 0 : t;
}

export default function DetectorDetails({ details, loading }) {
  // null = default alphabetical sort by detector ID
  const [sortDir, setSortDir] = useState(null);

  const toggleSort = () => {
    setSortDir((prev) => {
      if (prev === null) return "desc";
      if (prev === "desc") return "asc";
      return null;
    });
  };

  const sortedIds = useMemo(() => {
    if (!details) return [];
    const ids = Object.keys(details);
    if (sortDir === null) return ids.sort();
    return ids.sort((a, b) => {
      const diff = getTimestamp(details[a]) - getTimestamp(details[b]);
      return sortDir === "asc" ? diff : -diff;
    });
  }, [details, sortDir]);

  if (loading) {
    return (
      <Paper shadow="xs" p="md" radius="sm">
        <Stack gap="sm">
          <Skeleton height={20} />
          <Skeleton height={20} />
          <Skeleton height={20} />
        </Stack>
      </Paper>
    );
  }

  if (!details || Object.keys(details).length === 0) {
    return (
      <Paper shadow="xs" p="md" radius="sm">
        <Text c="dimmed" fs="italic">
          No detectors are currently deployed on edge.
        </Text>
      </Paper>
    );
  }

  return (
    <Paper shadow="xs" radius="sm" style={{ overflow: "hidden" }}>
      <Table striped highlightOnHover verticalSpacing="sm" horizontalSpacing="md">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Detector</Table.Th>
            <Table.Th style={{ textAlign: "center", whiteSpace: "nowrap" }}>
              Status{" "}
              <Tooltip
                label={STATUS_TOOLTIP}
                multiline
                w={380}
                withArrow
                position="bottom"
                styles={{ tooltip: { whiteSpace: "pre-line" } }}
              >
                <Text component="span" size="xs" c="dimmed" style={{ cursor: "help" }}>
                  &#9432;
                </Text>
              </Tooltip>
            </Table.Th>
            <Table.Th>Pipeline</Table.Th>
            <Table.Th>Edge Config</Table.Th>
            <Table.Th>
              <UnstyledButton onClick={toggleSort} className="sortable-header">
                <Group gap={4} wrap="nowrap">
                  <span>Last Updated</span>
                  <SortIcon direction={sortDir} />
                </Group>
              </UnstyledButton>
            </Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {sortedIds.map((id) => {
            const info = details[id] || {};
            return (
              <Table.Tr key={id}>
                <Table.Td>
                  <Stack gap={4}>
                    <Anchor
                      href={`https://dashboard.groundlight.ai/reef/detectors/${id}`}
                      target="_blank"
                      size="sm"
                      underline="always"
                    >
                      {id}
                    </Anchor>
                    <Text size="sm">{info.detector_name || "--"}</Text>
                    <Text size="sm" fw={500}>
                      {info.query || "--"}
                    </Text>
                    <Text size="sm" fw={700} c="dimmed">
                      {info.mode || "--"}
                    </Text>
                  </Stack>
                </Table.Td>
                <Table.Td style={{ textAlign: "center", whiteSpace: "nowrap" }}>
                  <StatusBadge status={info.status} statusDetail={info.status_detail} />
                </Table.Td>
                <Table.Td>
                  {info.pipeline_config ? (
                    <Text size="sm">{info.pipeline_config}</Text>
                  ) : (
                    <Text size="sm" c="dimmed">--</Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <EdgeConfigTable config={info.edge_inference_config} />
                </Table.Td>
                <Table.Td style={{ whiteSpace: "nowrap" }}>
                  <TimestampCell isoString={info.last_updated_time} />
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Paper>
  );
}
