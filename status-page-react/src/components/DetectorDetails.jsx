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
import { CodeHighlight } from "@mantine/code-highlight";

const TH_STYLE = {
  backgroundColor: "#3a383c",
  color: "#fff",
  whiteSpace: "nowrap",
};

const STATUS_CONFIG = {
  ready: { label: "Ready", color: "green", tooltip: "Model is loaded and serving inference requests." },
  updating: { label: "Updating", color: "blue", tooltip: "New model version deploying. Previous version still serving." },
  update_failed: { label: "Update Failed", color: "orange", tooltip: "New version failed to start. Previous version still serving." },
  initializing: { label: "Initializing", color: "yellow", tooltip: "Model is loading for the first time. Not yet available." },
  error: { label: "Error", color: "red", tooltip: "Model failed to start." },
};

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
      <Tooltip label={cfg.tooltip || status} withArrow position="bottom">
        <Badge
          variant="light"
          color={cfg.color}
          size="sm"
          style={{ whiteSpace: "nowrap", cursor: "default" }}
        >
          {cfg.label}
        </Badge>
      </Tooltip>
      {(status === "error" || status === "update_failed") && statusDetail && (
        <Text size="xs" c="dimmed">
          {statusDetail}
        </Text>
      )}
    </Stack>
  );
}

const YAML_COLLAPSED_HEIGHT = 80;

function PipelineCell({ yaml }) {
  const [expanded, setExpanded] = useState(false);
  if (!yaml) return <Text c="dimmed">--</Text>;
  return (
    <div style={{ position: "relative" }}>
      <div
        style={{
          maxHeight: expanded ? "none" : YAML_COLLAPSED_HEIGHT,
          overflow: "hidden",
        }}
      >
        <CodeHighlight
          code={yaml}
          language="yaml"
          copyLabel="Copy"
          copiedLabel="Copied"
          radius="sm"
          withBorder
          styles={{ code: { fontSize: "0.8em" } }}
        />
      </div>
      {!expanded && yaml.split("\n").length > 4 && (
        <UnstyledButton
          onClick={() => setExpanded(true)}
          style={{
            display: "block",
            width: "100%",
            textAlign: "center",
            fontSize: "0.75em",
            color: "#165a8a",
            paddingTop: 4,
          }}
        >
          Show more
        </UnstyledButton>
      )}
      {expanded && (
        <UnstyledButton
          onClick={() => setExpanded(false)}
          style={{
            display: "block",
            width: "100%",
            textAlign: "center",
            fontSize: "0.75em",
            color: "#165a8a",
            paddingTop: 4,
          }}
        >
          Show less
        </UnstyledButton>
      )}
    </div>
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
  // null = default sort by deployment creation time (oldest first)
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
    if (sortDir === null) return ids.sort((a, b) => {
      const timeCmp = (details[a].deploy_time || "").localeCompare(details[b].deploy_time || "");
      return timeCmp !== 0 ? timeCmp : a.localeCompare(b);
    });
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
    <Paper shadow="xs" radius="sm" style={{ overflowX: "auto" }}>
      <Table striped highlightOnHover verticalSpacing="sm" horizontalSpacing="md">
        <Table.Thead>
          <Table.Tr>
            <Table.Th style={TH_STYLE}>Detector</Table.Th>
            <Table.Th style={{ ...TH_STYLE, textAlign: "center" }}>Status</Table.Th>
            <Table.Th style={TH_STYLE}>Pipeline</Table.Th>
            <Table.Th style={TH_STYLE}>Edge Config</Table.Th>
            <Table.Th style={TH_STYLE}>
              <UnstyledButton onClick={toggleSort} className="sortable-header" style={{ color: "inherit" }}>
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
                <Table.Td style={{ verticalAlign: "top" }}>
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
                <Table.Td style={{ textAlign: "center", whiteSpace: "nowrap", verticalAlign: "top" }}>
                  <StatusBadge status={info.status} statusDetail={info.status_detail} />
                </Table.Td>
                <Table.Td style={{ verticalAlign: "top" }}>
                  <PipelineCell yaml={info.pipeline_config} />
                </Table.Td>
                <Table.Td style={{ verticalAlign: "top" }}>
                  <EdgeConfigTable config={info.edge_inference_config} />
                </Table.Td>
                <Table.Td style={{ whiteSpace: "nowrap", verticalAlign: "top" }}>
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
