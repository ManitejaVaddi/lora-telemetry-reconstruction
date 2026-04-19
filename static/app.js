const mapEl = document.getElementById("map");
const outputEl = document.getElementById("payload-output");
const logEl = document.getElementById("log");
const packetInputEl = document.getElementById("packet-input");
const searchInputEl = document.getElementById("search-input");
const timelineFilterEl = document.getElementById("timeline-filter");
const clusterToggleEl = document.getElementById("cluster-toggle");
const showPredictedToggleEl = document.getElementById("show-predicted-toggle");
const confidenceFilterEl = document.getElementById("confidence-filter");

let map;
let markers = [];
let items = [];

function initMap() {
  map = L.map('map').setView([17.385, 78.486], 13);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors'
  }).addTo(map);
}

initMap();

document.getElementById("load-demo").addEventListener("click", loadDemo);
document.getElementById("clear-view").addEventListener("click", clearView);
document.getElementById("send-packet").addEventListener("click", sendPacket);
searchInputEl.addEventListener("input", refreshView);
timelineFilterEl.addEventListener("change", refreshView);
clusterToggleEl.addEventListener("change", refreshView);
showPredictedToggleEl.addEventListener("change", refreshView);
confidenceFilterEl.addEventListener("input", refreshView);

function clearView() {
  items = [];
  markers.forEach(marker => map.removeLayer(marker));
  markers = [];
  outputEl.textContent = "No packet processed yet.";
  logEl.innerHTML = "";
}

async function loadDemo() {
  const response = await fetch("/demo-stream");
  const data = await response.json();
  clearView();
  const demoItems = data.items || [];
  if (demoItems.length) {
    outputEl.textContent = JSON.stringify(demoItems[demoItems.length - 1], null, 2);
  }
  // Animate adding points over time
  demoItems.forEach((item, index) => {
    setTimeout(() => {
      items.push(item);
      refreshView();
    }, index * 500); // 500ms delay between each
  });
}

async function sendPacket() {
  const packet = packetInputEl.value.trim();
  if (!packet) {
    return;
  }

  const response = await fetch("/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ packet }),
  });

  const payload = await response.json();
  items.push(payload);
  outputEl.textContent = JSON.stringify(payload, null, 2);
  // Color code based on status
  packetInputEl.style.borderColor = payload.packet_status === "verified" ? "green" : payload.packet_status === "fragmented" ? "red" : "orange";
  refreshView();
}

function refreshView() {
  const filteredItems = getFilteredItems();
  drawMap(filteredItems);
  renderLog(filteredItems);
}

function getFilteredItems() {
  const query = searchInputEl.value.trim().toLowerCase();
  const timeline = timelineFilterEl.value;
  const showPredicted = showPredictedToggleEl.checked;
  const minConfidence = parseFloat(confidenceFilterEl.value);
  const latestTimestamp = getLatestTimestamp(items);

  return items.filter((item) => {
    const matchesSearch =
      !query ||
      [item.node_id, item.source, item.packet_status, ...(item.notes || [])]
        .join(" ")
        .toLowerCase()
        .includes(query);

    if (!matchesSearch) {
      return false;
    }

    if (timeline === "all" || !latestTimestamp) {
      // pass
    } else {
      const itemTime = parseTimestamp(item.timestamp);
      if (!itemTime) {
        return false;
      }

      const hours = timeline === "24h" ? 24 : 24 * 7;
      const cutoff = latestTimestamp.getTime() - hours * 60 * 60 * 1000;
      if (itemTime.getTime() < cutoff) {
        return false;
      }
    }

    if (!showPredicted && item.packet_status !== "verified") {
      return false;
    }

    if ((item.confidence || 0) < minConfidence) {
      return false;
    }

    return true;
  });
}

function getLatestTimestamp(list) {
  const timestamps = list.map((item) => parseTimestamp(item.timestamp)).filter(Boolean);
  if (!timestamps.length) {
    return null;
  }
  return new Date(Math.max(...timestamps.map((value) => value.getTime())));
}

function parseTimestamp(value) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function renderLog(filteredItems) {
  logEl.innerHTML = "";
  if (!filteredItems.length) {
    logEl.innerHTML = `<div class="log-empty">No packets match the current filters.</div>`;
    return;
  }

  [...filteredItems].reverse().forEach((payload) => {
    const row = document.createElement("div");
    row.className = "log-row";
    row.innerHTML = `
      <span class="status ${payload.packet_status}">${payload.packet_status}</span>
      <strong>${payload.node_id}</strong>
      <span>${payload.timestamp}</span>
      <span>${formatCoord(payload.lat)}, ${formatCoord(payload.lon)}</span>
      <span>${payload.source || "unknown"} | confidence ${payload.confidence}</span>
    `;
    logEl.appendChild(row);
  });
}

function drawMap(filteredItems) {
  markers.forEach((marker) => map.removeLayer(marker));
  markers = [];

  const drawable = filteredItems.filter((item) => typeof item.lat === "number" && typeof item.lon === "number");
  if (!drawable.length) {
    return;
  }

  const group = L.featureGroup();
  const pathPoints = [];

  drawable.forEach((item) => {
    const color = item.packet_status === "verified" ? "blue" : "orange";
    const size = 6 + (item.confidence || 1) * 8;
    const marker = L.circleMarker([item.lat, item.lon], {
      color,
      fillColor: color,
      fillOpacity: Math.max(0.3, Math.min(item.confidence || 1, 1)),
      radius: size / 2,
      weight: 1,
    }).addTo(map);
    marker.bindPopup(makeTooltip(item));
    markers.push(marker);
    group.addLayer(marker);
    pathPoints.push([item.lat, item.lon]);
  });

  if (pathPoints.length > 1) {
    const line = L.polyline(pathPoints, { color: "rgba(10,108,116,0.7)", weight: 3 });
    line.addTo(map);
    markers.push(line);
    group.addLayer(line);
  }

  map.fitBounds(group.getBounds().pad(0.1));
}

function buildClusters(plotted) {
  if (plotted.length < 5) {
    return plotted.map((item) => ({ ...item, count: 1, kind: "point" }));
  }

  const cells = new Map();
  const cellSize = 10;

  plotted.forEach((item) => {
    const key = `${Math.floor(item.x / cellSize)}:${Math.floor(item.y / cellSize)}`;
    const cell = cells.get(key) || [];
    cell.push(item);
    cells.set(key, cell);
  });

  return Array.from(cells.values()).map((group) => {
    if (group.length === 1) {
      return { ...group[0], count: 1, kind: "point" };
    }

    const latest = [...group].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp)).at(-1);
    return {
      ...latest,
      kind: "cluster",
      count: group.length,
      x: average(group.map((item) => item.x)),
      y: average(group.map((item) => item.y)),
      clusterNodes: [...new Set(group.map((item) => item.node_id))],
      notes: [`Cluster of ${group.length} packets`],
    };
  });
}

function average(values) {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function makeLine(x1, y1, x2, y2, status) {
  const line = document.createElement("div");
  const dx = x2 - x1;
  const dy = y2 - y1;
  const length = Math.sqrt(dx * dx + dy * dy);
  const angle = Math.atan2(dy, dx) * (180 / Math.PI);
  line.className = `track ${status}`;
  line.style.width = `${length}%`;
  line.style.left = `${x1}%`;
  line.style.top = `${y1}%`;
  line.style.transform = `rotate(${angle}deg)`;
  return line;
}

function makeTooltip(item) {
  if (item.kind === "cluster") {
    return `Cluster (${item.count}) | nodes: ${item.clusterNodes.join(", ")} | latest: ${item.timestamp}`;
  }
  return `${item.node_id} | ${item.packet_status} | ${item.source} | ${item.timestamp}`;
}

function formatCoord(value) {
  return typeof value === "number" ? value.toFixed(6) : "n/a";
}
