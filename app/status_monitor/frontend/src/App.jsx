import { useState, useEffect, useRef, useCallback, useMemo } from "react";
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
  SegmentedControl,
  CopyButton,
  ActionIcon,
  Tooltip,
} from "@mantine/core";
import { CodeHighlight } from "@mantine/code-highlight";
import yaml from "yaml";
import DetectorDetails from "./components/DetectorDetails";
import ResourceUsage from "./components/ResourceUsage";
import { DARK_HEADER_STYLE } from "./sharedStyles";

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

function CopyIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}
function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

const CODE_BG = "#f6f6f6";

// Single code-block widget used for every "view this dict as code" section on
// the page. Renders a slim dark header (yaml/json SegmentedControl on the
// left, copy button on the right) above a borderless CodeHighlight using the
// Stack Overflow Light syntax theme.
//
//   languages        - non-empty array containing "yaml", "json", or both,
//                      in the order tabs should appear. Single-language
//                      sections still get the same header so the language is
//                      labeled (Mantine renders a single-item SegmentedControl
//                      as a non-interactive label).
//   defaultLanguage  - which tab is selected first. Must be one of `languages`.
function CodeSection({ title, data, languages, defaultLanguage, loading }) {
  const codes = useMemo(() => {
    const parsed = parseSection(data) ?? {};
    return {
      yaml: yaml.stringify(parsed),
      json: stringifyCompactArrays(parsed),
    };
  }, [data]);
  const [lang, setLang] = useState(defaultLanguage);
  const isLoading = loading || data == null;
  return (
    <Stack gap="xs">
      <Text style={SECTION_TITLE_STYLE}>{title}</Text>
      {isLoading ? (
        <GenericSectionSkeleton />
      ) : (
        <Paper
          withBorder
          radius="sm"
          className="theme-stackoverflow-light"
          style={{ overflow: "hidden", background: CODE_BG }}
        >
          <Group justify="space-between" align="center" px="xs" py={6} style={DARK_HEADER_STYLE}>
            {languages.length > 1 ? (
              <SegmentedControl
                size="xs"
                value={lang}
                onChange={setLang}
                classNames={{
                  root: "dark-pill-toggle-root",
                  indicator: "dark-pill-toggle-indicator",
                  label: "dark-pill-toggle-label",
                }}
                data={languages.map((l) => ({ label: l, value: l }))}
              />
            ) : (
              <div />
            )}
            <CopyButton value={codes[lang]} timeout={1500}>
              {({ copied, copy }) => (
                <Tooltip label={copied ? "Copied" : "Copy"} withArrow position="left">
                  <ActionIcon
                    variant="subtle"
                    size="sm"
                    onClick={copy}
                    aria-label="Copy"
                    style={{ color: "rgba(255,255,255,0.7)" }}
                  >
                    {copied ? <CheckIcon /> : <CopyIcon />}
                  </ActionIcon>
                </Tooltip>
              )}
            </CopyButton>
          </Group>
          <CodeHighlight code={codes[lang]} language={lang} withCopyButton={false} background={CODE_BG} />
        </Paper>
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

          <CodeSection
            title="Device Information"
            data={metrics?.device_info}
            languages={["json"]}
            defaultLanguage="json"
            loading={loading}
          />

          <CodeSection
            title="Configuration"
            data={edgeConfig}
            languages={["yaml", "json"]}
            defaultLanguage="yaml"
            loading={loading}
          />

          <CodeSection
            title="Activity Metrics"
            data={metrics?.activity_metrics}
            languages={["json"]}
            defaultLanguage="json"
            loading={loading}
          />
          <CodeSection
            title="Kubernetes Stats"
            data={metrics?.k3s_stats}
            languages={["json"]}
            defaultLanguage="json"
            loading={loading}
          />
          <CodeSection
            title="Failed Escalations"
            data={metrics?.failed_escalations}
            languages={["json"]}
            defaultLanguage="json"
            loading={loading}
          />
        </Stack>
      </Container>
    </>
  );
}
