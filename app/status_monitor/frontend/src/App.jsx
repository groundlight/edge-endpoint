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

const REFRESH_MS = 5_000; // TODO: revert to 10_000 before merging

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
  const code = data ? JSON.stringify(parseSection(data), null, 2) : "";
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
          <JsonSection title="Device Information" data={metrics?.device_info} loading={loading} />

          <Stack gap="xs">
            <Text style={SECTION_TITLE_STYLE}>Detector Details</Text>
            <DetectorDetails details={detectorDetails} loading={loading} />
          </Stack>

          <Stack gap="xs">
            <Text style={SECTION_TITLE_STYLE}>Resource Usage by Detector</Text>
            <ResourceUsage resourceData={resources} detectorDetails={detectorDetails} loading={loading} />
          </Stack>

          <JsonSection title="Activity Metrics" data={metrics?.activity_metrics} loading={loading} />
          <JsonSection title="Kubernetes Stats" data={metrics?.k3s_stats} loading={loading} />
          <JsonSection title="Failed Escalations" data={metrics?.failed_escalations} loading={loading} />
        </Stack>
      </Container>
    </>
  );
}
