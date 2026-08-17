"use strict";

// API状態と描画状態を一か所で管理し、画面操作のたびにSVGを再構築する。
const state = {
  map: null, route: [], blocked: new Set(), currentPosition: null,
  latestObservedAt: null, refreshingPosition: false, searchingRoute: false, routeUpdateCount: 0,
  simulation: { running: false, route: null, runId: 0 },
};
const $ = (id) => document.getElementById(id);

function apiBase() { return $("api-url").value.replace(/\/$/, ""); }

async function request(path, options = {}) {
  const response = await fetch(`${apiBase()}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = body.detail?.message || body.detail || `HTTP ${response.status}`;
    throw new Error(message);
  }
  return body;
}

function setStatus(message, error = false) {
  $("status").textContent = message;
  $("status").classList.toggle("error", error);
}

function coordinates() {
  const nodes = state.map.nodes;
  const xs = nodes.map((node) => node.x), ys = nodes.map((node) => node.y);
  const bounds = { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
  const width = 900, height = 560, padding = 75;
  const scale = Math.min(
    (width - padding * 2) / Math.max(bounds.maxX - bounds.minX, 1),
    (height - padding * 2) / Math.max(bounds.maxY - bounds.minY, 1),
  );
  return {
    width, height, scale, bounds, padding,
    point: (x, y) => ({ x: padding + (x - bounds.minX) * scale, y: padding + (y - bounds.minY) * scale }),
  };
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
}

function routeEdgeIds() {
  const ids = new Set();
  for (let index = 0; index < state.route.length - 1; index += 1) {
    const from = state.route[index].id, to = state.route[index + 1].id;
    const edge = state.map.edges.find((item) =>
      (item.from === from && item.to === to) || (item.bidirectional && item.from === to && item.to === from));
    if (edge) ids.add(edge.id);
  }
  return ids;
}

function drawMap() {
  if (!state.map) return;
  const svg = $("facility-map"), geometry = coordinates();
  const nodeById = Object.fromEntries(state.map.nodes.map((node) => [node.id, node]));
  const highlighted = routeEdgeIds();
  svg.replaceChildren();
  svg.setAttribute("viewBox", `0 0 ${geometry.width} ${geometry.height}`);

  // 経路を通常通路より後から描画することで、探索結果を前面に表示する。
  [...state.map.edges].sort((edge) => highlighted.has(edge.id) ? 1 : -1).forEach((edge) => {
    const from = geometry.point(nodeById[edge.from].x, nodeById[edge.from].y);
    const to = geometry.point(nodeById[edge.to].x, nodeById[edge.to].y);
    const classes = ["edge"];
    if (highlighted.has(edge.id)) classes.push("route-edge");
    if (state.blocked.has(edge.id)) classes.push("blocked-edge");
    svg.append(svgElement("line", { x1: from.x, y1: from.y, x2: to.x, y2: to.y, class: classes.join(" ") }));
    const label = svgElement("text", { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 - 8, class: "edge-label", "text-anchor": "middle" });
    label.textContent = `${edge.id} / ${edge.distance}m`;
    svg.append(label);
  });

  state.map.nodes.forEach((node) => {
    const point = geometry.point(node.x, node.y);
    const group = svgElement("g", { class: `node${$("destination").value === node.id ? " destination" : ""}`, tabindex: "0" });
    group.append(svgElement("circle", { cx: point.x, cy: point.y, r: 10 }));
    const text = svgElement("text", { x: point.x, y: point.y - 18, "text-anchor": "middle" });
    text.textContent = node.name;
    group.append(text);
    group.addEventListener("click", (event) => { event.stopPropagation(); $("destination").value = node.id; drawMap(); });
    svg.append(group);
  });

  if (state.currentPosition) {
    const point = geometry.point(state.currentPosition.x, state.currentPosition.y);
    svg.append(svgElement("circle", { cx: point.x, cy: point.y, r: 8, class: "position-marker" }));
  }
  $("empty-map").hidden = true;
}

function renderObstacles() {
  const container = $("obstacle-list");
  container.replaceChildren();
  state.map.edges.forEach((edge) => {
    const row = document.createElement("div"); row.className = "obstacle-item";
    const description = document.createElement("div");
    description.innerHTML = `<strong>${edge.id}</strong><small>${edge.from} → ${edge.to}</small>`;
    const label = document.createElement("label"); label.className = "switch";
    const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.checked = state.blocked.has(edge.id);
    checkbox.addEventListener("change", () => toggleObstacle(edge.id, checkbox.checked, checkbox));
    label.append(checkbox, document.createElement("span")); row.append(description, label); container.append(row);
  });
}

async function loadMap() {
  try {
    const floorId = $("floor-id").value;
    const [map, obstacles] = await Promise.all([request(`/api/maps/${encodeURIComponent(floorId)}`), request("/api/obstacles")]);
    state.map = map; state.route = []; state.blocked = new Set(obstacles.filter((item) => item.blocked).map((item) => item.edge_id));
    $("map-title").textContent = `${map.name} 経路地図`;
    $("destination").replaceChildren(...map.nodes.filter((node) => ["room", "elevator", "stairs", "entrance"].includes(node.type)).map((node) => {
      const option = document.createElement("option"); option.value = node.id; option.textContent = `${node.name}（${node.id}）`; return option;
    }));
    // 移動シミュレーションをすぐ確認できるよう、仮地図では教室Bを初期目的地にする。
    if (map.nodes.some((node) => node.id === "room-b")) $("destination").value = "room-b";
    $("health-dot").classList.add("online"); $("health-label").textContent = "API接続済み";
    renderObstacles(); drawMap(); setStatus(`${map.nodes.length}地点・${map.edges.length}通路を読み込みました`);
  } catch (error) {
    $("health-dot").classList.remove("online"); $("health-label").textContent = "接続エラー"; setStatus(error.message, true);
  }
}

async function registerPosition() {
  try {
    const payload = {
      client_id: $("client-id").value, floor_id: $("floor-id").value,
      x: Number($("position-x").value), y: Number($("position-y").value),
      variance: Number($("variance").value), observed_at: new Date().toISOString(),
    };
    const result = await request("/api/mock/positions", { method: "POST", body: JSON.stringify(payload) });
    state.currentPosition = result.position;
    $("nearest-result").textContent = `最寄り: ${result.nearest_node.name}（${result.nearest_node.distance}m）`;
    drawMap(); setStatus("現在位置を登録しました");
    if ($("auto-route").checked && $("destination").value) await searchRoute({ silent: true });
  } catch (error) { setStatus(error.message, true); }
}

async function refreshLatestPosition() {
  if (!state.map || !$("client-id").value || state.refreshingPosition) return;
  state.refreshingPosition = true;
  try {
    const result = await request(`/api/positions/${encodeURIComponent($("client-id").value)}`);
    const previous = state.currentPosition;
    state.currentPosition = result.position;
    const observationChanged = state.latestObservedAt !== result.observed_at;
    state.latestObservedAt = result.observed_at;
    $("nearest-result").textContent = `最寄り: ${result.nearest_node.name}（${result.nearest_node.distance}m） / ${result.source}`;
    const moved = !previous || previous.x !== result.position.x || previous.y !== result.position.y;
    // LIVEが有効なら、初回探索前でも位置変化と同時に現在地から目的地まで再探索する。
    if (moved && $("auto-route").checked && $("destination").value) await searchRoute({ silent: true });
    else if (moved) drawMap();
    if (observationChanged) {
      const observed = new Date(result.observed_at).toLocaleTimeString("ja-JP");
      setStatus(`位置情報を受信しました（${observed}）`);
    }
  } catch (error) {
    // 未登録の404はモック送信開始前の正常な状態なので、画面のエラー表示を上書きしない。
  }
  finally { state.refreshingPosition = false; }
}

async function searchRoute(options = {}) {
  if (state.searchingRoute) return;
  state.searchingRoute = true;
  try {
    const result = await request("/api/routes/search", { method: "POST", body: JSON.stringify({
      client_id: $("client-id").value, destination_node_id: $("destination").value,
    }) });
    state.route = result.route; $("total-distance").textContent = `${result.total_distance} m`;
    $("guidance").replaceChildren(...result.guidance.map((step) => {
      const item = document.createElement("li"); item.textContent = step.message; return item;
    }));
    state.routeUpdateCount += 1;
    $("route-updated-at").textContent =
      `● 自動更新 #${state.routeUpdateCount}　${result.start_node.name} → ${result.destination_node.name}　${new Date().toLocaleTimeString("ja-JP")}`;
    // 更新の瞬間を地図全体の発光で知らせ、リアルタイム動作を目視確認しやすくする。
    $("map-container").classList.remove("route-flash");
    requestAnimationFrame(() => $("map-container").classList.add("route-flash"));
    setTimeout(() => $("map-container").classList.remove("route-flash"), 650);
    drawMap();
    if (!options.silent) setStatus(`${result.start_node.name}から${result.destination_node.name}まで探索しました`);
  } catch (error) { state.route = []; drawMap(); setStatus(error.message, true); }
  finally { state.searchingRoute = false; }
}

async function toggleObstacle(edgeId, blocked, checkbox) {
  checkbox.disabled = true;
  try {
    await request("/api/obstacles", { method: "POST", body: JSON.stringify({ edge_id: edgeId, blocked, reason: blocked ? "test-web" : null, source: "test-web" }) });
    blocked ? state.blocked.add(edgeId) : state.blocked.delete(edgeId);
    drawMap(); setStatus(`${edgeId}を${blocked ? "通行止めに設定" : "再開"}しました`);
    if (state.currentPosition && $("destination").value) await searchRoute();
  } catch (error) { checkbox.checked = !blocked; setStatus(error.message, true); }
  finally { checkbox.disabled = false; }
}

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function simulationPayload(route, position, scenario) {
  const timestamp = new Date().toISOString();
  const locations = scenario === "location-unavailable" ? [] : [{
    x: String(position.x), y: String(position.y), floorPlanId: route.floorPlanId,
    floorPlanName: route.floorPlanName, time: timestamp, variance: 1.5, rssiRecords: [],
  }];
  return {
    version: "3.0", secret: "test-web-secret", type: "WiFi",
    data: { networkId: "L_TEST_WEB", observations: [{
      clientMac: $("client-id").value, manufacturer: "Test Web Simulator", ssid: "D1-Navigation",
      locations, latestRecord: { time: timestamp, nearestApMac: null, nearestApRssi: null },
    }] },
  };
}

async function startSimulation() {
  if (state.simulation.running) return;
  let runId = null;
  try {
    if (!state.simulation.route) {
      const response = await fetch("movement_route.json");
      if (!response.ok) throw new Error("移動経路ファイルを読み込めません");
      state.simulation.route = await response.json();
    }
    state.simulation.running = true;
    runId = ++state.simulation.runId;
    $("simulation-start").disabled = true; $("simulation-stop").disabled = false;
    $("simulation-badge").textContent = "RUNNING"; $("simulation-badge").classList.add("running");
    const route = state.simulation.route;
    let index = 0;
    while (state.simulation.running && runId === state.simulation.runId) {
      const scenario = $("simulation-scenario").value;
      // 逸脱シナリオでは、案内された曲がり角を無視して直進する専用座標列を使う。
      const positions = scenario === "off-route" ? route.offRoutePositions : route.positions;
      const sourcePosition = positions[index];
      const position = scenario === "stationary" ? route.positions[0] : sourcePosition;
      const result = await request("/api/scanning", {
        method: "POST", body: JSON.stringify(simulationPayload(route, position, scenario)),
      });
      const scenarioLabel = scenario === "off-route" ? "経路逸脱 " : "";
      $("simulation-badge").textContent = scenario === "off-route" ? "OFF ROUTE" : "RUNNING";
      $("simulation-badge").classList.toggle("off-route", scenario === "off-route");
      const label = scenario === "location-unavailable" ? "位置取得失敗" : `${scenarioLabel}x=${position.x}, y=${position.y}`;
      $("simulation-status").textContent = `${index + 1}/${positions.length}　${label}　HTTP 200（updated=${result.updated}）`;
      $("simulation-progress-bar").style.width = `${((index + 1) / positions.length) * 100}%`;
      index += 1;
      if (index >= positions.length) {
        if ($("simulation-loop").checked) index = 0;
        else break;
      }
      const seconds = Math.max(.2, Number($("simulation-interval").value) || 1.5);
      await wait(seconds * 1000);
    }
  } catch (error) {
    setStatus(`シミュレーター: ${error.message}`, true);
  } finally {
    // 停止直後に再開始された場合、古いループが新しい実行を停止しないようIDを確認する。
    if (runId !== null && runId === state.simulation.runId) finishSimulation();
  }
}

function stopSimulation() {
  state.simulation.running = false;
  state.simulation.runId += 1;
  finishSimulation();
}

function finishSimulation() {
  state.simulation.running = false;
  $("simulation-start").disabled = false; $("simulation-stop").disabled = true;
  $("simulation-badge").textContent = "STOPPED";
  $("simulation-badge").classList.remove("running", "off-route");
}

$("facility-map").addEventListener("click", (event) => {
  if (!state.map) return;
  const geometry = coordinates(), point = $("facility-map").createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
  const local = point.matrixTransform($("facility-map").getScreenCTM().inverse());
  $("position-x").value = (geometry.bounds.minX + (local.x - geometry.padding) / geometry.scale).toFixed(1);
  $("position-y").value = (geometry.bounds.minY + (local.y - geometry.padding) / geometry.scale).toFixed(1);
  setStatus("地図上の座標を入力欄へ反映しました。登録ボタンを押してください");
});
$("reload-button").addEventListener("click", loadMap);
$("position-button").addEventListener("click", registerPosition);
$("route-button").addEventListener("click", searchRoute);
$("destination").addEventListener("change", async () => {
  drawMap();
  // 目的地変更時は次の測位更新を待たず、保持中の現在位置から直ちに再探索する。
  if ($("auto-route").checked && state.currentPosition) await searchRoute({ silent: true });
});
$("auto-route").addEventListener("change", async () => {
  $("route-updated-at").textContent = $("auto-route").checked ? "自動更新を待機しています" : "自動更新は停止中です";
  if ($("auto-route").checked && state.currentPosition && $("destination").value) await searchRoute({ silent: true });
});
$("simulation-start").addEventListener("click", startSimulation);
$("simulation-stop").addEventListener("click", stopSimulation);
loadMap();
// Scanning APIから更新された最新位置を取得し、SVGマーカーへ反映する。
setInterval(refreshLatestPosition, 1000);
