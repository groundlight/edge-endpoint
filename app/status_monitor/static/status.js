const createDetectorLink = (detectorId) => {
    const link = document.createElement("a");
    link.href = `https://dashboard.groundlight.ai/reef/detectors/${detectorId}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = detectorId;
    return link;
};

const renderPipeline = (pipelineConfig) => {
    if (!pipelineConfig) {
        return document.createTextNode("—");
    }

    const element = document.createElement("code");
    element.textContent = pipelineConfig;
    return element;
};

const formatTimestamp = (isoString) => {
    if (!isoString) {
        return null;
    }

    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) {
        return null;
    }

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
    const getPart = (type) => parts.find((p) => p.type === type)?.value || "";
    const dateStr = `${getPart("month")}/${getPart("day")}/${getPart("year")}`;
    const timeStr = `${getPart("hour")}:${getPart("minute")}:${getPart("second")} ${getPart("dayPeriod")} ${getPart(
        "timeZoneName",
    )}`.trim();

    const diffMs = Date.now() - date.getTime();
    const diffSec = Math.max(0, Math.floor(diffMs / 1000));
    let relative;
    if (diffSec < 60) {
        relative = `${diffSec} second${diffSec === 1 ? "" : "s"} ago`;
    } else if (diffSec < 3600) {
        const mins = Math.floor(diffSec / 60);
        relative = `${mins} minute${mins === 1 ? "" : "s"} ago`;
    } else if (diffSec < 86400) {
        const hours = Math.floor(diffSec / 3600);
        relative = `${hours} hour${hours === 1 ? "" : "s"} ago`;
    } else {
        const days = Math.floor(diffSec / 86400);
        relative = `${days} day${days === 1 ? "" : "s"} ago`;
    }

    return { date: dateStr, time: timeStr, relative };
};

const parseIfJson = (value) => {
    if (typeof value === "string") {
        try {
            return JSON.parse(value);
        } catch (_) {
            return value;
        }
    }
    return value;
};

const parseSection = (section) => {
    if (!section) {
        return section;
    }
    const parsed = { ...section };
    for (const [key, value] of Object.entries(parsed)) {
        parsed[key] = parseIfJson(value);
    }
    return parsed;
};

const createEdgeConfigTable = (config) => {
    if (!config || Object.keys(config).length === 0) {
        return document.createTextNode("—");
    }

    const table = document.createElement("table");
    table.className = "edge-config-table";
    Object.entries(config).forEach(([key, value]) => {
        const row = document.createElement("tr");
        const keyCell = document.createElement("td");
        keyCell.textContent = key;
        const valueCell = document.createElement("td");
        valueCell.textContent = value;
        row.append(keyCell, valueCell);
        table.appendChild(row);
    });

    return table;
};

const STATUS_DISPLAY = {
    ready: { label: "Ready", className: "status-ready" },
    updating: { label: "Updating", className: "status-updating" },
    update_failed: { label: "Update Failed", className: "status-update-failed" },
    initializing: { label: "Initializing", className: "status-initializing" },
    error: { label: "Error", className: "status-error" },
};

const renderStatusBadge = (status, statusDetail) => {
    const wrapper = document.createElement("div");
    const display = STATUS_DISPLAY[status] || { label: status || "Unknown", className: "status-initializing" };

    const badge = document.createElement("span");
    badge.className = `status-badge ${display.className}`;
    badge.textContent = display.label;
    wrapper.appendChild(badge);

    if ((status === "error" || status === "update_failed") && statusDetail) {
        const detail = document.createElement("div");
        detail.className = "status-detail";
        detail.textContent = statusDetail;
        wrapper.appendChild(detail);
    }

    return wrapper;
};

const renderDetectorDetails = (rawDetails) => {
    const container = document.getElementById("detector-details");
    container.innerHTML = "";
    container.classList.remove("skeleton");

    const details = parseIfJson(rawDetails) || {};
    const detectorIds = Object.keys(details);

    if (detectorIds.length === 0) {
        const emptyState = document.createElement("div");
        emptyState.className = "empty-state";
        emptyState.textContent = "No detectors are currently deployed on edge.";
        container.appendChild(emptyState);
        return;
    }

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");

    const STATUS_TOOLTIP =
        "Ready: Model is loaded and serving inference requests.\n" +
        "Updating: New model version deploying. Previous version still serving.\n" +
        "Update Failed: New version failed to start. Previous version still serving.\n" +
        "Initializing: Model is loading for the first time. Not yet available.\n" +
        "Error: Model failed to start.";

    ["Detector", "Status", "Pipeline", "Edge Config", "Last Updated"].forEach((heading) => {
        const th = document.createElement("th");
        if (heading === "Status") {
            th.textContent = heading + " ";
            const icon = document.createElement("span");
            icon.className = "status-info-icon";
            icon.textContent = "\u24D8";
            icon.setAttribute("data-tooltip", STATUS_TOOLTIP);
            th.appendChild(icon);
        } else {
            th.textContent = heading;
        }
        headerRow.appendChild(th);
    });

    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    detectorIds.sort().forEach((detectorId) => {
        const info = details[detectorId] || {};
        const row = document.createElement("tr");

        const detectorCell = document.createElement("td");
        detectorCell.className = "detector-column";
        const idLine = document.createElement("div");
        idLine.appendChild(createDetectorLink(detectorId));
        const nameLine = document.createElement("div");
        nameLine.className = "detector-name";
        nameLine.textContent = info.detector_name || "—";
        const queryLine = document.createElement("div");
        queryLine.className = "detector-query";
        queryLine.textContent = info.query || "—";
        const modeLine = document.createElement("div");
        modeLine.textContent = info.mode ? info.mode : "—";
        modeLine.className = "detector-mode";
        detectorCell.append(idLine, nameLine, queryLine, modeLine);
        row.appendChild(detectorCell);

        const statusCell = document.createElement("td");
        statusCell.className = "status-column";
        statusCell.appendChild(renderStatusBadge(info.status, info.status_detail));
        row.appendChild(statusCell);

        const pipelineCell = document.createElement("td");
        pipelineCell.appendChild(renderPipeline(info.pipeline_config));
        row.appendChild(pipelineCell);

        const edgeConfigCell = document.createElement("td");
        const edgeConfigContent = createEdgeConfigTable(info.edge_inference_config);
        edgeConfigCell.appendChild(edgeConfigContent);
        row.appendChild(edgeConfigCell);

        const lastUpdatedCell = document.createElement("td");
        lastUpdatedCell.className = "last-updated";
        const timestampInfo = formatTimestamp(info.last_updated_time);
        if (!timestampInfo) {
            lastUpdatedCell.textContent = "—";
        } else {
            const dateLine = document.createElement("div");
            dateLine.textContent = timestampInfo.date;

            const timeLine = document.createElement("div");
            timeLine.textContent = timestampInfo.time;

            const relativeLine = document.createElement("div");
            relativeLine.className = "timestamp-relative";
            relativeLine.textContent = `(${timestampInfo.relative})`;

            lastUpdatedCell.append(dateLine, timeLine, relativeLine);
        }
        row.appendChild(lastUpdatedCell);

        tbody.appendChild(row);
    });

    table.appendChild(tbody);
    container.appendChild(table);
};

// -- VRAM Usage --

const VRAM_COLORS = [
    "#4A90D9", "#D94A6B", "#D9A94A", "#4AD9A9", "#9B59B6",
    "#E67E22", "#1ABC9C", "#E74C3C", "#3498DB", "#2ECC71",
];
const VRAM_FREE_COLOR = "#E0E0E0";

const formatBytes = (bytes) => {
    if (bytes == null) return "--";
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 1) return `${gb.toFixed(1)} GB`;
    const mb = bytes / (1024 * 1024);
    return `${mb.toFixed(0)} MB`;
};

const createDonutChart = (slices, centerText) => {
    const size = 180;
    const strokeWidth = 28;
    const radius = (size - strokeWidth) / 2;
    const circumference = 2 * Math.PI * radius;

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", size);
    svg.setAttribute("height", size);
    svg.setAttribute("viewBox", `0 0 ${size} ${size}`);

    let offset = 0;
    slices.forEach(({ fraction, color }) => {
        if (fraction <= 0) return;
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", size / 2);
        circle.setAttribute("cy", size / 2);
        circle.setAttribute("r", radius);
        circle.setAttribute("fill", "none");
        circle.setAttribute("stroke", color);
        circle.setAttribute("stroke-width", strokeWidth);
        const dashLen = fraction * circumference;
        circle.setAttribute("stroke-dasharray", `${dashLen} ${circumference - dashLen}`);
        circle.setAttribute("stroke-dashoffset", `${-offset * circumference}`);
        svg.appendChild(circle);
        offset += fraction;
    });

    const container = document.createElement("div");
    container.className = "vram-donut-container";
    container.appendChild(svg);

    const label = document.createElement("div");
    label.className = "vram-donut-label";
    const val = document.createElement("div");
    val.className = "used-value";
    val.textContent = centerText;
    const cap = document.createElement("div");
    cap.className = "used-caption";
    cap.textContent = "used";
    label.append(val, cap);
    container.appendChild(label);

    return container;
};

const renderVramUsage = (vramData, detectorDetails) => {
    const container = document.getElementById("vram-usage");
    container.innerHTML = "";

    if (vramData.error) {
        const msg = document.createElement("div");
        msg.className = "empty-state";
        msg.textContent = vramData.error;
        container.appendChild(msg);
        return;
    }

    const gpus = vramData.gpus || [];
    const detectors = vramData.detectors || [];

    if (gpus.length === 0) {
        const msg = document.createElement("div");
        msg.className = "empty-state";
        msg.textContent = "No GPU data available.";
        container.appendChild(msg);
        return;
    }

    const detNameMap = {};
    if (detectorDetails) {
        const parsed = parseIfJson(detectorDetails) || {};
        Object.entries(parsed).forEach(([id, info]) => {
            detNameMap[id] = info.detector_name || id;
        });
    }

    gpus.forEach((gpu) => {
        const card = document.createElement("div");
        card.className = "vram-gpu-card";

        const title = document.createElement("div");
        title.className = "vram-gpu-title";
        title.textContent = `GPU ${gpu.index}: ${gpu.name} (${formatBytes(gpu.total_bytes)})`;
        card.appendChild(title);

        const totalBytes = gpu.total_bytes;
        const slices = [];
        const legendItems = [];
        let accountedBytes = 0;

        detectors.forEach((det, i) => {
            const color = VRAM_COLORS[i % VRAM_COLORS.length];
            const bytes = det.total_vram_bytes || 0;
            accountedBytes += bytes;
            slices.push({ fraction: bytes / totalBytes, color });
            const name = detNameMap[det.detector_id] || det.detector_id;
            legendItems.push({ color, label: name, value: formatBytes(bytes) });
        });

        const loadingBytes = vramData.loading_vram_bytes || 0;
        accountedBytes += loadingBytes;
        if (loadingBytes > 0) {
            const loadingColor = "#555555";
            slices.push({ fraction: loadingBytes / totalBytes, color: loadingColor });
            legendItems.push({ color: loadingColor, label: "Loading Detector Models", value: formatBytes(loadingBytes) });
        }

        const otherBytes = Math.max(0, gpu.used_bytes - accountedBytes);
        if (otherBytes > 0) {
            const otherColor = "#B0B0B0";
            slices.push({ fraction: otherBytes / totalBytes, color: otherColor });
            legendItems.push({ color: otherColor, label: "Other", value: formatBytes(otherBytes) });
        }

        const freeBytes = Math.max(0, totalBytes - gpu.used_bytes);
        slices.push({ fraction: freeBytes / totalBytes, color: VRAM_FREE_COLOR });
        legendItems.push({ color: VRAM_FREE_COLOR, label: "Free", value: formatBytes(freeBytes) });

        const row = document.createElement("div");
        row.className = "vram-chart-row";

        const usedPct = ((gpu.used_bytes / totalBytes) * 100).toFixed(0);
        row.appendChild(createDonutChart(slices, `${usedPct}%`));

        const legend = document.createElement("div");
        legend.className = "vram-legend";
        legendItems.forEach(({ color, label, value }) => {
            const item = document.createElement("div");
            item.className = "vram-legend-item";
            const swatch = document.createElement("div");
            swatch.className = "vram-legend-swatch";
            swatch.style.backgroundColor = color;
            const labelEl = document.createElement("span");
            labelEl.className = "vram-legend-label";
            labelEl.textContent = label;
            const valueEl = document.createElement("span");
            valueEl.className = "vram-legend-value";
            valueEl.textContent = value;
            item.append(swatch, labelEl, valueEl);
            legend.appendChild(item);
        });
        row.appendChild(legend);

        card.appendChild(row);
        container.appendChild(card);
    });
};

let cachedDetectorDetails = null;

const fetchVram = () => {
    fetch("/status/vram.json")
        .then((r) => r.ok ? r.json() : Promise.reject(r.statusText))
        .then((data) => renderVramUsage(data, cachedDetectorDetails))
        .catch((err) => console.error("Error fetching VRAM data:", err));
};

const fetchAll = (showLoading = false) => {
    const detectorDetailsContainer = document.getElementById("detector-details");
    if (showLoading) {
        detectorDetailsContainer.classList.add("skeleton");
        document.getElementById("loading").style.display = "block";
        document.getElementById("error").style.display = "none";
    }

    fetch("/status/metrics.json")
        .then((response) => {
            if (!response.ok) throw new Error("Network response was not ok");
            return response.json();
        })
        .then((data) => {
            document.getElementById("device-info").textContent = JSON.stringify(parseSection(data.device_info), null, 2);
            document.getElementById("activity-metrics").textContent = JSON.stringify(
                parseSection(data.activity_metrics), null, 2,
            );
            document.getElementById("failed-escalations").textContent = JSON.stringify(
                parseSection(data.failed_escalations), null, 2,
            );
            document.getElementById("k3s-stats").textContent = JSON.stringify(parseSection(data.k3s_stats), null, 2);

            cachedDetectorDetails = data.detector_details;
            renderDetectorDetails(data.detector_details);
            document.getElementById("loading").style.display = "none";
            document.getElementById("error").style.display = "none";
        })
        .catch((error) => {
            detectorDetailsContainer.classList.remove("skeleton");
            if (showLoading) {
                document.getElementById("loading").style.display = "none";
            }
            document.getElementById("error").style.display = "block";
            console.error("Error fetching metrics:", error);
        })
        .finally(() => {
            fetchVram();
        });
};

let refreshIntervalId = null;

const startAutoRefresh = () => {
    if (refreshIntervalId !== null) {
        return;
    }
    refreshIntervalId = setInterval(() => fetchAll(false), 1000);
};

const stopAutoRefresh = () => {
    if (refreshIntervalId === null) {
        return;
    }
    clearInterval(refreshIntervalId);
    refreshIntervalId = null;
};

document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        stopAutoRefresh();
    } else {
        fetchAll(false);
        startAutoRefresh();
    }
});

document.addEventListener("DOMContentLoaded", () => {
    fetchAll(true);
    startAutoRefresh();
});

