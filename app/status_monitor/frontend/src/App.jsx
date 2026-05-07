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
import CollapsibleSection from "./components/CollapsibleSection";
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

// Walk a section's top-level keys and JSON.parse any string value that
// happens to be valid JSON. Some metrics fields are deliberately stringified
// on the backend (via json.dumps) to keep OpenSearch from exploding nested
// objects into thousands of indexed fields. For human display we want to
// undo that so the data renders as nested JSON instead of a wall of
// backslash-escaped quotes. Strings that aren't valid JSON (e.g. plain
// timestamps, Python repr lists) are passed through unchanged.
const rehydrateSection = (section) => {
  if (!section || typeof section !== "object") return section;
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

// Stable references for CodeSection's `languages` prop so memoization isn't
// invalidated by fresh array literals on every render.
const JSON_ONLY = ["json"];
const YAML_OR_JSON = ["yaml", "json"];

// Serializer for each supported CodeSection language. Each entry must accept
// the parsed payload object and return a string.
const LANGUAGE_SERIALIZERS = {
  yaml: (parsed) => yaml.stringify(parsed),
  json: (parsed) => stringifyCompactArrays(parsed),
};

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

// Body widget for "view this dict as code" sections. Renders a slim dark
// header (yaml/json SegmentedControl on the left when there is more than one
// language, copy button on the right) above a borderless CodeHighlight whose
// syntax colors come from the .theme-code class in code-themes.css. The
// section title and surrounding chrome (collapse trigger, gap) are owned by
// the wrapping CollapsibleSection.
//
//   languages  - non-empty ordered array containing "yaml", "json", or both.
//                The first entry is the initially-selected tab. Single-
//                language sections render with no toggle (just the copy
//                button), since the language is implicit.
//   error      - if true and data is missing, render a "Failed to load"
//                message instead of the perpetual skeleton.
//   rehydrate  - if true, JSON.parse top-level string values that look like
//                JSON before serializing. Use this for sections whose backend
//                deliberately stringifies subfields to dodge OpenSearch field
//                explosion (e.g. Kubernetes Stats, Activity Metrics).
function CodeSection({ data, languages, loading, error = false, rehydrate = false }) {
  // Each serializer is wrapped individually so a failure in one language tab
  // (e.g. an exotic value yaml.stringify can't handle) doesn't take down the
  // others. Only the requested languages are computed -- skipping the unused
  // serializer for single-language sections.
  const codes = useMemo(() => {
    const parsed = (rehydrate ? rehydrateSection(data) : data) ?? {};
    return Object.fromEntries(
      languages.map((l) => {
        try {
          return [l, LANGUAGE_SERIALIZERS[l](parsed)];
        } catch (e) {
          return [l, `// Failed to render as ${l}: ${e.message}`];
        }
      })
    );
  }, [data, languages, rehydrate]);
  const [lang, setLang] = useState(languages[0]);
  const showError = error && data == null && !loading;
  const showSkeleton = !showError && (loading || data == null);
  const multipleLanguages = languages.length > 1;
  if (showSkeleton) return <GenericSectionSkeleton />;
  if (showError) {
    return (
      <Alert color="red" variant="light">
        Failed to load.
      </Alert>
    );
  }
  return (
    <Paper
      withBorder
      radius="sm"
      className="theme-code"
      style={{ overflow: "hidden" }}
    >
      <Group
        justify={multipleLanguages ? "space-between" : "flex-end"}
        align="center"
        px="xs"
        py={6}
        style={DARK_HEADER_STYLE}
      >
        {multipleLanguages && (
          <SegmentedControl
            size="xs"
            value={lang}
            onChange={setLang}
            aria-label="Code format"
            classNames={{
              root: "dark-pill-toggle-root",
              indicator: "dark-pill-toggle-indicator",
              label: "dark-pill-toggle-label",
            }}
            data={languages.map((l) => ({ label: l, value: l }))}
          />
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
      <CodeHighlight code={codes[lang]} language={lang} withCopyButton={false} />
    </Paper>
  );
}

export default function App() {
  const [metrics, setMetrics] = useState(null);
  const [resources, setResources] = useState(null);
  const [edgeConfig, setEdgeConfig] = useState(null);
  const [edgeConfigError, setEdgeConfigError] = useState(false);
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
      if (res.ok) {
        setEdgeConfig(await res.json());
        setEdgeConfigError(false);
      } else {
        setEdgeConfigError(true);
      }
    } catch {
      setEdgeConfigError(true);
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
          <CollapsibleSection title="Detector Details">
            <DetectorDetails details={detectorDetails} loading={loading} />
          </CollapsibleSection>

          <CollapsibleSection title="Resource Usage by Detector">
            <ResourceUsage resourceData={resources} detectorDetails={detectorDetails} loading={loading} />
          </CollapsibleSection>

          <CollapsibleSection title="Device Information">
            <CodeSection data={metrics?.device_info} languages={JSON_ONLY} loading={loading} />
          </CollapsibleSection>

          <CollapsibleSection title="Configuration">
            <CodeSection
              data={edgeConfig}
              languages={YAML_OR_JSON}
              loading={loading}
              error={edgeConfigError}
            />
          </CollapsibleSection>

          <CollapsibleSection title="Activity Metrics">
            <CodeSection data={metrics?.activity_metrics} languages={JSON_ONLY} loading={loading} rehydrate />
          </CollapsibleSection>

          <CollapsibleSection title="Kubernetes Stats">
            <CodeSection data={metrics?.k3s_stats} languages={JSON_ONLY} loading={loading} rehydrate />
          </CollapsibleSection>

          <CollapsibleSection title="Failed Escalations">
            <CodeSection data={metrics?.failed_escalations} languages={JSON_ONLY} loading={loading} />
          </CollapsibleSection>
        </Stack>
      </Container>
    </>
  );
}
