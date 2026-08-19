const $ = id => document.getElementById(id);
const esc = value => String(value ?? "-").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
const formatTime = value => value ? new Date(value).toLocaleTimeString("ja-JP", {hour12:false}) : "-";
const pointText = value => value ? `(${Number(value.x).toFixed(2)}, ${Number(value.y).toFixed(2)})` : "-";
const mock = {route:null, status:"stopped", index:0, timer:null, nextAt:null, logs:[]};
let backend = null;
let map = null;
let refreshing = false;

async function request(path, options={}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail?.message || body.detail || `${response.status} ${response.statusText}`);
  return {body, status:response.status, statusText:response.statusText};
}

function setMessage(message, error=false) {
  $("global-message").textContent=message;
  $("global-message").style.color=error ? "#ef6464" : "#91a099";
}

function currentClientId() { return $("mock-client").value.trim() || "mock-user-01"; }
function currentSession() {
  if (!backend) return null;
  const related=backend.sessions.filter(item=>item.client_id===currentClientId());
  return related.find(item=>item.status==="active") || related.sort((a,b)=>new Date(b.updated_at)-new Date(a.updated_at))[0] || null;
}

function setMockStatus(status) {
  mock.status=status;
  const labels={running:"RUNNING",paused:"PAUSED",stopped:"STOPPED",completed:"COMPLETED"};
  $("mock-state").textContent=labels[status];
  $("mock-state").className=`state ${status}`;
  $("mock-start").disabled=status==="running";
  $("mock-pause").disabled=status!=="running";
}

function addMockLog(client, coordinate, result, error=false) {
  mock.logs.unshift({time:new Date(),client,coordinate,result,error});
  mock.logs=mock.logs.slice(0,100);
  $("mock-logs").innerHTML=mock.logs.length ? mock.logs.map(item=>`<div class="mock-log ${item.error?"error":""}"><span>${formatTime(item.time)}</span><span>${esc(item.client)} → ${esc(item.coordinate)}</span><strong>${esc(item.result)}</strong></div>`).join("") : "<p>モック送信待機中</p>";
}

async function generateAndSend(x, y, scenario, label) {
  const client=currentClientId();
  try {
    const generated=await request("/api/dev/mock/payload", {method:"POST",body:JSON.stringify({client_id:client,x,y,scenario})});
    const result=await request("/api/scanning", {method:"POST",body:JSON.stringify(generated.body.payload)});
    const location=generated.body.payload.data.observations[0].locations[0];
    const coordinate=location ? `(${location.x}, ${location.y})` : "(測位失敗)";
    const status=`${result.status} ${result.statusText || "OK"}`.trim();
    $("mock-http").textContent=`POST /api/scanning  ${status}`;
    addMockLog(client,coordinate,status);
    if (label) $("manual-result").textContent=`${label} ${coordinate} を送信しました`;
    await refreshStatus();
    return {coordinate,status};
  } catch(error) {
    $("mock-http").textContent=`ERROR ${error.message}`;
    addMockLog(client,`(${x}, ${y})`,error.message,true);
    setMessage(error.message,true);
    throw error;
  }
}

function intervalMs() { return Math.max(.5,Number($("mock-interval").value)||5)*1000; }
function clearSchedule() { if(mock.timer)clearTimeout(mock.timer); mock.timer=null; mock.nextAt=null; }
function scheduleNext() {
  clearSchedule();
  if(mock.status!=="running")return;
  mock.nextAt=Date.now()+intervalMs();
  mock.timer=setTimeout(sendAutomatic,intervalMs());
}

async function sendAutomatic() {
  clearSchedule();
  if(mock.status!=="running" || !mock.route?.points.length)return;
  const points=mock.route.points;
  if(mock.index>=points.length) {
    if($("mock-loop").checked) mock.index=0;
    else { setMockStatus("completed"); return; }
  }
  const progressIndex=mock.index;
  const scenario=$("mock-scenario").value;
  const point=scenario==="stationary" ? points[0] : points[progressIndex];
  $("mock-count").textContent=`${progressIndex+1} / ${points.length}`;
  $("mock-coordinate").textContent=`(${point.x}, ${point.y})`;
  $("mock-point-name").textContent=point.node_name || `移動点 ${progressIndex+1}`;
  $("mock-progress-bar").style.width=`${(progressIndex+1)/points.length*100}%`;
  try { await generateAndSend(point.x,point.y,scenario); }
  catch { setMockStatus("paused"); return; }
  mock.index=progressIndex+1;
  if(mock.index>=points.length && !$("mock-loop").checked) setMockStatus("completed");
  else scheduleNext();
}

function startMock(reset=false) {
  if (!mock.route) return setMessage("モック経路を読み込めません",true);
  clearSchedule();
  if(reset || mock.status==="completed" || mock.index>=mock.route.points.length) mock.index=0;
  setMockStatus("running");
  sendAutomatic();
}
function pauseMock(){ if(mock.status!=="running")return; clearSchedule(); setMockStatus("paused"); }
function stopMock(){ clearSchedule(); setMockStatus("stopped"); $("mock-next").textContent="-"; }

async function loadSources() {
  const [routeResponse,mapResponse]=await Promise.all([request("/api/dev/mock/route"),request("/api/maps/floor-1")]);
  mock.route=routeResponse.body; map=mapResponse.body;
  $("map-title").textContent=`${map.name} デバッグ地図`;
  $("manual-point").innerHTML=mock.route.points.map(item=>`<option value="${item.index}">${item.index+1}. ${esc(item.node_name||"移動点")} (${item.x}, ${item.y})</option>`).join("");
  $("obstacle-edge").innerHTML=map.edges.map(edge=>`<option value="${esc(edge.id)}">${esc(edge.id)}: ${esc(edge.from)} → ${esc(edge.to)}</option>`).join("");
  $("mock-count").textContent=`0 / ${mock.route.points.length}`;
  $("selectable-list").innerHTML=`<strong>目的地候補:</strong> ${map.nodes.filter(n=>n.selectable).map(n=>`<span>${esc(n.name)} (${esc(n.id)})</span>`).join("")}`;
  drawMap();
}

function svg(tag,attributes={}) { const element=document.createElementNS("http://www.w3.org/2000/svg",tag); Object.entries(attributes).forEach(([key,value])=>element.setAttribute(key,value)); return element; }
function drawMap() {
  if(!map)return;
  const root=$("facility-map"), width=900, height=470, pad=70;
  root.replaceChildren(); root.setAttribute("viewBox",`0 0 ${width} ${height}`); $("map-empty").style.display="none";
  const xs=map.nodes.map(n=>n.x),ys=map.nodes.map(n=>n.y),minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
  const sx=x=>pad+(x-minX)/(maxX-minX||1)*(width-pad*2), sy=y=>height-pad-(y-minY)/(maxY-minY||1)*(height-pad*2);
  const nodes=Object.fromEntries(map.nodes.map(n=>[n.id,n]));
  const session=currentSession(), routePairs=new Set();
  if(session) for(let i=0;i<session.current_route.length-1;i++){const a=session.current_route[i].id,b=session.current_route[i+1].id;routePairs.add(`${a}|${b}`);routePairs.add(`${b}|${a}`);}
  const blocked=new Set(backend?.obstacles.map(item=>item.edge_id)||[]);
  map.edges.forEach(edge=>{const a=nodes[edge.from],b=nodes[edge.to];if(!a||!b)return;const onRoute=routePairs.has(`${edge.from}|${edge.to}`);root.append(svg("line",{x1:sx(a.x),y1:sy(a.y),x2:sx(b.x),y2:sy(b.y),class:`map-edge${onRoute?" route":""}${blocked.has(edge.id)?" blocked":""}`}));});
  map.nodes.forEach(node=>{const group=svg("g",{class:`map-node${node.selectable?" selectable":""}${session?.destination_id===node.id?" destination":""}`});group.append(svg("circle",{cx:sx(node.x),cy:sy(node.y),r:10}));const text=svg("text",{x:sx(node.x)+13,y:sy(node.y)-13});text.textContent=node.name;group.append(text);root.append(group);});
  const client=backend?.clients.find(item=>item.client_id===currentClientId());
  const position=session?.current_position || client?.latest_position;
  if(position) root.append(svg("circle",{cx:sx(position.x),cy:sy(position.y),r:8,class:"current-marker"}));
}

function renderPosition() {
  const client=backend.clients.find(item=>item.client_id===currentClientId()), session=currentSession();
  if(!client){$("position-details").innerHTML=`<p class="empty">${esc(currentClientId())}の位置情報を待っています</p>`;return;}
  const p=client.latest_position, state=session?.position_state, current=session?.current_position;
  $("position-details").innerHTML=`<div class="data-grid"><div><span>client_id</span><strong>${esc(client.client_id)}</strong></div><div><span>floor</span><strong>${esc(p.floor_id)}</strong></div><div><span>Latest / source</span><strong>${pointText(p)} / ${esc(p.source)}</strong></div><div><span>observed_at</span><strong>${formatTime(p.observed_at)}</strong></div><div><span>Meraki</span><strong>${pointText(state?.meraki_position)}</strong></div><div><span>PDR</span><strong>${pointText(state?.pdr_position)}</strong></div><div><span>Fused</span><strong>${pointText(state?.fused_position)}</strong></div><div><span>Map matched</span><strong>${pointText(current)}</strong></div><div><span>Matched edge</span><strong>${esc(current?.matched_edge?.id)}</strong></div><div><span>Edge distance</span><strong>${current?.distance_from_edge_m ?? "-"} m</strong></div></div>`;
}

function renderSession() {
  const session=currentSession();
  if(!session){$("session-status").textContent="NONE";$("session-status").className="state stopped";$("session-details").innerHTML="<p class=\"empty\">Androidからのナビ開始を待っています</p>";return;}
  $("session-status").textContent=session.status.toUpperCase(); $("session-status").className=`state ${session.status==="active"?"running":session.status==="arrived"?"completed":"stopped"}`;
  $("session-details").innerHTML=`<div class="data-grid"><div><span>session_id</span><strong>${esc(session.session_id)}</strong></div><div><span>client_id</span><strong>${esc(session.client_id)}</strong></div><div><span>destination</span><strong>${esc(session.destination_id)}</strong></div><div><span>current position</span><strong>${pointText(session.current_position)}</strong></div><div><span>remaining</span><strong>${session.remaining_distance_m} m</strong></div><div><span>route changed</span><strong>${esc(session.route_changed)}</strong></div><div><span>next guidance</span><strong>${esc(session.next_guidance?.message)}</strong></div><div><span>target heading</span><strong>${session.next_guidance?.target_heading_deg == null ? "-" : `${session.next_guidance.target_heading_deg}°`}</strong></div><div><span>updated</span><strong>${formatTime(session.updated_at)}</strong></div></div><p class="route-text">${session.current_route.map(node=>esc(node.name)).join("<br>↓<br>")||"-"}</p>${session.status==="active"?`<button class="session-finish danger" data-session="${esc(session.session_id)}">セッション終了</button>`:""}`;
}

function renderHttpLogs() {
  const logs=backend.communication_logs;
  $("http-logs").innerHTML=logs.length ? logs.map(item=>{const cls=item.source.startsWith("Android")?"src-android":item.source.startsWith("Meraki")?"src-meraki":item.source==="Dev Panel"?"src-dev":"";return `<tr><td>${formatTime(item.timestamp)}</td><td class="${cls}">${esc(item.source)}</td><td><strong>${esc(item.method)}</strong> ${esc(item.path)}</td><td class="${item.status_code>=400?"http-error":""}">${item.status_code}</td><td>${item.duration_ms}</td></tr>`;}).join("") : `<tr><td colspan="5">通信待機中</td></tr>`;
  const android=logs.find(item=>item.source.startsWith("Android")); $("android-api").textContent=android?`${android.method} ${android.path}`:"Navigation API待機中";
}

function renderStatus() {
  $("backend-time").textContent=formatTime(backend.current_time); $("android-last").textContent=formatTime(backend.last_access.android); $("scanning-last").textContent=formatTime(backend.last_access.scanning); $("state-last").textContent=formatTime(backend.last_access.state_poll); $("active-count").textContent=backend.active_navigation_sessions;
  $("obstacle-list").innerHTML=backend.obstacles.length?backend.obstacles.map(item=>`<div><strong>${esc(item.edge_id)}</strong> — ${esc(item.reason)}</div>`).join(""):"通行止めなし";
  renderPosition(); renderSession(); renderHttpLogs(); drawMap();
}

async function refreshStatus(){if(refreshing)return;refreshing=true;try{backend=(await request("/api/dev/status")).body;renderStatus();}catch(error){setMessage(error.message,true);}finally{refreshing=false;}}

$("mock-start").onclick=()=>startMock(false); $("mock-pause").onclick=pauseMock; $("mock-stop").onclick=stopMock; $("mock-replay").onclick=()=>startMock(true);
$("send-point").onclick=async()=>{const item=mock.route?.points[Number($("manual-point").value)];if(!item)return;try{await generateAndSend(item.x,item.y,$("mock-scenario").value,item.node_name||`移動点 ${item.index+1}`);}catch{}};
$("send-coordinate").onclick=async()=>{try{await generateAndSend(Number($("manual-x").value),Number($("manual-y").value),$("mock-scenario").value,"指定座標");}catch{}};
async function setObstacle(blocked){try{await request("/api/obstacles",{method:"POST",body:JSON.stringify({edge_id:$("obstacle-edge").value,blocked,reason:$("obstacle-reason").value||null,source:"dev-console"})});await refreshStatus();}catch(error){setMessage(error.message,true);}}
$("block-edge").onclick=()=>setObstacle(true); $("unblock-edge").onclick=()=>setObstacle(false); $("refresh-button").onclick=refreshStatus;
$("session-details").onclick=async event=>{const button=event.target.closest(".session-finish");if(!button)return;try{await request(`/api/navigation/sessions/${encodeURIComponent(button.dataset.session)}`,{method:"DELETE"});await refreshStatus();}catch(error){setMessage(error.message,true);}};
$("clear-mock-log").onclick=()=>{mock.logs=[];$("mock-logs").innerHTML="<p>モック送信待機中</p>";};
$("reset-button").onclick=async()=>{if(!confirm("開発用の位置、セッション、通行止め、ログをリセットしますか？"))return;stopMock();mock.index=0;mock.logs=[];try{await request("/api/dev/reset",{method:"POST",body:"{}"});$("mock-logs").innerHTML="<p>モック送信待機中</p>";$("mock-progress-bar").style.width="0";$("mock-count").textContent=`0 / ${mock.route?.points.length||0}`;$("mock-coordinate").textContent="-";$("mock-point-name").textContent="-";$("mock-http").textContent="-";await refreshStatus();setMessage("開発状態をリセットしました");}catch(error){setMessage(error.message,true);}};
$("mock-client").addEventListener("change",()=>{renderStatus();});

setInterval(()=>{$("mock-next").textContent=mock.nextAt&&mock.status==="running"?`${Math.max(0,(mock.nextAt-Date.now())/1000).toFixed(1)}秒後`:"-";},200);
setMockStatus("stopped");
Promise.all([loadSources(),refreshStatus()]).catch(error=>setMessage(error.message,true));
setInterval(refreshStatus,2000);
