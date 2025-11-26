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

const createEdgeConfigList = (config) => {
    if (!config || Object.keys(config).length === 0) {
        return document.createTextNode("—");
    }

    const list = document.createElement("ul");
    Object.entries(config).forEach(([key, value]) => {
        const item = document.createElement("li");
        item.textContent = `${key}: ${value}`;
        list.appendChild(item);
    });
    return list;
};

const renderDetectorDetails = (rawDetails) => {
    const container = document.getElementById("detector-details");
    container.innerHTML = "";

    const details = parseIfJson(rawDetails) || {};
    const detectorIds = Object.keys(details);

    if (detectorIds.length === 0) {
        const emptyState = document.createElement("div");
        emptyState.className = "empty-state";
        emptyState.textContent = "No detector details available.";
        container.appendChild(emptyState);
        return;
    }

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");

    ["Detector ID", "Pipeline", "Last Updated", "Mode", "Query", "Edge Config"].forEach((heading) => {
        const th = document.createElement("th");
        th.textContent = heading;
        headerRow.appendChild(th);
    });

    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    detectorIds.sort().forEach((detectorId) => {
        const info = details[detectorId] || {};
        const row = document.createElement("tr");

        const cells = [
            detectorId,
            info.pipeline_config || "—",
            info.last_updated_time || "—",
            info.mode || "—",
            info.query || "—",
        ];

        cells.forEach((value) => {
            const td = document.createElement("td");
            td.textContent = value;
            row.appendChild(td);
        });

        const edgeConfigCell = document.createElement("td");
        const edgeConfigContent = createEdgeConfigList(info.edge_inference_config);
        edgeConfigCell.appendChild(edgeConfigContent);
        row.appendChild(edgeConfigCell);

        tbody.appendChild(row);
    });

    table.appendChild(tbody);
    container.appendChild(table);
};

document.addEventListener("DOMContentLoaded", () => {
    fetch("/status/metrics.json")
        .then((response) => {
            if (!response.ok) {
                throw new Error("Network response was not ok");
            }
            return response.json();
        })
        .then((data) => {
            document.getElementById("device-info").textContent = JSON.stringify(parseSection(data.device_info), null, 2);
            document.getElementById("activity-metrics").textContent = JSON.stringify(
                parseSection(data.activity_metrics),
                null,
                2,
            );
            document.getElementById("k3s-stats").textContent = JSON.stringify(parseSection(data.k3s_stats), null, 2);

            renderDetectorDetails(data.detector_details);
            document.getElementById("loading").style.display = "none";
        })
        .catch((error) => {
            document.getElementById("loading").style.display = "none";
            document.getElementById("error").style.display = "block";
            console.error("Error fetching metrics:", error);
        });
});

