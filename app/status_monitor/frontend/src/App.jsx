import { useState, useEffect, useRef, useCallback } from "react";
import {
  Container,
  Title,
  Text,
  Loader,
  Alert,
  Group,
  Stack,
  Paper,
  Skeleton,
} from "@mantine/core";
import { CodeHighlight } from "@mantine/code-highlight";
import DetectorDetails from "./components/DetectorDetails";
import ResourceUsage from "./components/ResourceUsage";

// Faster polling in dev is helpful when iterating, slow down polling in prod
const REFRESH_MS = import.meta.env.DEV ? 1_000 : 10_000;

const parseIfJson = (value) => {
  if (typeof value === "string") {
    try {
      return JSON.parse(value);
    } catch {
      return value;
    }
  }
  return value;
};

const parseSection = (section) => {
  if (!section) return section;
  const parsed = { ...section };
  for (const [key, value] of Object.entries(parsed)) {
    parsed[key] = parseIfJson(value);
  }
  return parsed;
};

// Pretty-print JSON like JSON.stringify(value, null, indent), but keep arrays
// of pure primitives on a single line so e.g. histogram counts don't take up
// an entire vertical column.
const stringifyCompactArrays = (value, indent = 2) => {
  const pad = (depth) => " ".repeat(depth * indent);
  const isPrimitive = (v) =>
    v === null || ["string", "number", "boolean"].includes(typeof v);
  const fmt = (v, depth) => {
    if (Array.isArray(v) && v.every(isPrimitive)) {
      return `[${v.map((x) => JSON.stringify(x)).join(", ")}]`;
    }
    if (Array.isArray(v)) {
      if (v.length === 0) return "[]";
      const inner = v.map((x) => pad(depth + 1) + fmt(x, depth + 1));
      return `[\n${inner.join(",\n")}\n${pad(depth)}]`;
    }
    if (v && typeof v === "object") {
      const entries = Object.entries(v);
      if (entries.length === 0) return "{}";
      const lines = entries.map(
        ([k, x]) => `${pad(depth + 1)}${JSON.stringify(k)}: ${fmt(x, depth + 1)}`
      );
      return `{\n${lines.join(",\n")}\n${pad(depth)}}`;
    }
    return JSON.stringify(v);
  };
  return fmt(value, 0);
};

const SECTION_TITLE_STYLE = { fontSize: "1.25em", fontWeight: 500, color: "#1F1D23" };

function GenericSectionSkeleton() {
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

function JsonSection({ title, data, loading }) {
  const code = data ? stringifyCompactArrays(parseSection(data)) : "";
  return (
    <Stack gap="xs">
      <Text style={SECTION_TITLE_STYLE}>{title}</Text>
      {loading ? (
        <GenericSectionSkeleton />
      ) : (
        <CodeHighlight
          code={code}
          language="json"
          copyLabel="Copy"
          copiedLabel="Copied"
          radius="sm"
          withBorder
        />
      )}
    </Stack>
  );
}

export default function App() {
  const [metrics, setMetrics] = useState(null);
  const [resources, setResources] = useState(null);
  const [edgeConfig, setEdgeConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const intervalRef = useRef(null);

  const fetchAll = useCallback(async (showLoading = false) => {
    if (showLoading) {
      setLoading(true);
      setError(false);
    }
    try {
      const res = await fetch("/status/metrics.json");
      if (!res.ok) throw new Error("Network response was not ok");
      setMetrics(await res.json());
      setLoading(false);
      setError(false);
    } catch {
      if (showLoading) setLoading(false);
      setError(true);
    }

    try {
      const res = await fetch("/status/resources.json");
      if (res.ok) setResources(await res.json());
    } catch {
      // Resource data is optional
    }

    try {
      const res = await fetch("/edge-config");
      if (res.ok) setEdgeConfig(await res.json());
    } catch {
      // Edge config is optional
    }
  }, []);

  useEffect(() => {
    fetchAll(true);

    const start = () => {
      if (intervalRef.current) return;
      intervalRef.current = setInterval(() => fetchAll(false), REFRESH_MS);
    };
    const stop = () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        fetchAll(false);
        start();
      }
    };

    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [fetchAll]);

  const detectorDetails = metrics ? parseIfJson(metrics.detector_details) : null;

  return (
    <>
      <header className="app-header">
        <Group gap="sm">
          <img
            src="/status/static/icon_gold_dark.svg"
            alt="Groundlight logo"
            className="header-logo"
          />
          <Title order={2} fw={400} c="var(--yellow)">
            Groundlight Edge Endpoint Status
          </Title>
        </Group>
      </header>

      <Container size="lg" py="xl">
        {loading && (
          <Group justify="center" py="lg">
            <Loader color="yellow" />
            <Text>Loading status...</Text>
          </Group>
        )}
        {error && (
          <Alert color="red" variant="light" mb="lg">
            Failed to load metrics data.
          </Alert>
        )}

        <Stack gap="xl">
          <Stack gap="xs">
            <Text style={SECTION_TITLE_STYLE}>Detector Details</Text>
            <DetectorDetails details={detectorDetails} loading={loading} />
          </Stack>

          <Stack gap="xs">
            <Text style={SECTION_TITLE_STYLE}>Resource Usage by Detector</Text>
            <ResourceUsage resourceData={resources} detectorDetails={detectorDetails} loading={loading} />
          </Stack>

          <JsonSection title="Device Information" data={metrics?.device_info} loading={loading} />

          <JsonSection title="Edge Endpoint Configuration" data={edgeConfig} loading={loading} />

          <JsonSection title="Activity Metrics" data={metrics?.activity_metrics} loading={loading} />
          <JsonSection title="Kubernetes Stats" data={metrics?.k3s_stats} loading={loading} />
          <JsonSection title="Failed Escalations" data={metrics?.failed_escalations} loading={loading} />
        </Stack>
      </Container>
    </>
  );
}
