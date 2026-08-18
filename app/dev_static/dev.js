const $ = (id) => document.getElementById(id);
let latestStatus = null;
let refreshing = false;

const esc = (value) => String(value ?? "-").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
const time = (value) => value ? new Date(value).toLocaleString("ja-JP", {hour12:false}) : "-";
const point = (value) => value ? `(${Number(value.x).toFixed(2)}, ${Number(value.y).toFixed(2)})` : "-";
const setResult = (id, message, error=false) => { const el=$(id); el.textContent=message; el.className=`result ${error ? "error" : "success"}`; };

async function api(path, options={}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail?.message || body.detail || `HTTP ${response.status}`);
  return body;
}

function renderClients(clients) {
  $("clients-badge").textContent=clients.length;
  $("clients").className="";
  $("clients").innerHTML=clients.length ? clients.map(client => {
    const p=client.latest_position, s=client.navigation_session, ps=s?.position_state;
    return `<article class="client"><h3>${esc(client.client_id)}</h3><div class="details">
      <div><span>Latest</span><strong>${point(p)} / ${esc(p.source)}</strong></div><div><span>Floor</span><strong>${esc(p.floor_id)}</strong></div><div><span>Variance</span><strong>${esc(p.variance)} m</strong></div>
      <div><span>Meraki</span><strong>${point(ps?.meraki_position)}</strong></div><div><span>PDR</span><strong>${point(ps?.pdr_position)}</strong></div><div><span>Fused</span><strong>${point(ps?.fused_position)}</strong></div>
      <div><span>Map Matched</span><strong>${point(s?.current_position)}</strong></div><div><span>Edge</span><strong>${esc(s?.current_position?.matched_edge?.id)}</strong></div><div><span>Distance from Edge</span><strong>${s ? esc(s.current_position.distance_from_edge_m) + " m" : "-"}</strong></div>
      <div><span>Observed</span><strong>${time(p.observed_at)}</strong></div></div></article>`;
  }).join("") : `<p class="empty">位置情報はありません</p>`;
}

function renderSessions(sessions) {
  $("sessions-badge").textContent=sessions.length;
  $("sessions").className="";
  $("sessions").innerHTML=sessions.length ? sessions.map(s => `<article class="session"><h3>${esc(s.session_id)}</h3><div class="details">
    <div><span>Client</span><strong>${esc(s.client_id)}</strong></div><div><span>Status</span><strong>${esc(s.status)}</strong></div><div><span>Destination</span><strong>${esc(s.destination_id)}</strong></div>
    <div><span>Current Position</span><strong>${point(s.current_position)}</strong></div><div><span>Remaining</span><strong>${esc(s.remaining_distance_m)} m</strong></div><div><span>Last Sequence</span><strong>${esc(s.last_sequence)}</strong></div>
    <div><span>Next Guidance</span><strong>${esc(s.next_guidance?.message)}</strong></div><div><span>Route Changed</span><strong>${esc(s.route_changed)}</strong></div><div><span>Updated</span><strong>${time(s.updated_at)}</strong></div>
    <div><span>Created</span><strong>${time(s.created_at)}</strong></div></div><p class="route">${s.current_route.length ? s.current_route.map(n=>esc(n.id)).join(" → ") : "-"}</p>
    ${s.status === "active" ? `<div class="session-actions"><button class="finish-session danger" data-session="${esc(s.session_id)}">セッション終了</button></div>` : ""}</article>`).join("") : `<p class="empty">セッションはありません</p>`;
  const select=$("movement-session"), selected=select.value, active=sessions.filter(s=>s.status==="active");
  select.innerHTML=active.length ? active.map(s=>`<option value="${esc(s.session_id)}">${esc(s.session_id)} / ${esc(s.client_id)}</option>`).join("") : `<option value="">実行中セッションなし</option>`;
  if (active.some(s=>s.session_id===selected)) select.value=selected;
}

function renderLogs(logs) {
  $("logs").innerHTML=logs.length ? logs.map(log => { const sourceClass=log.source.startsWith("Android")?"source-android":log.source.startsWith("Meraki")?"source-meraki":log.source==="Dev Panel"?"source-dev":""; return `<tr><td>${time(log.timestamp)}</td><td class="${sourceClass}">${esc(log.source)}</td><td><strong>${esc(log.method)}</strong> ${esc(log.path)}</td><td class="${log.status_code>=400?"status-error":""}">${esc(log.status_code)}</td><td>${esc(log.duration_ms)}</td><td>${esc(log.client_id)}<br>${esc(log.session_id)}</td></tr>`; }).join("") : `<tr><td colspan="6" class="empty">通信履歴はありません</td></tr>`;
}

function render(status) {
  latestStatus=status; $("online").textContent=status.backend_status; $("current-time").textContent=time(status.current_time);
  $("client-count").textContent=status.active_clients; $("session-count").textContent=status.active_navigation_sessions; $("obstacle-count").textContent=status.blocked_edges;
  $("last-android").textContent=time(status.last_access.android); $("last-scanning").textContent=time(status.last_access.scanning); $("last-movement").textContent=time(status.last_access.movement); $("last-state").textContent=time(status.last_access.state_poll);
  renderClients(status.clients); renderSessions(status.sessions); renderLogs(status.communication_logs);
  $("obstacles").innerHTML=status.obstacles.length ? status.obstacles.map(o=>`<div><strong>${esc(o.edge_id)}</strong> — ${esc(o.reason)}</div>`).join("") : "通行止めなし";
}

async function refresh() { if(refreshing)return; refreshing=true; try { render(await api("/api/dev/status")); $("global-message").textContent="自動更新中"; $("global-message").className="message success"; } catch(e) { $("global-message").textContent=e.message; $("global-message").className="message error"; } finally { refreshing=false; } }

$("refresh").onclick=refresh;
$("send-mock").onclick=async()=>{ try { const body={client_id:$("mock-client").value,floor_id:$("mock-floor").value,x:Number($("mock-x").value),y:Number($("mock-y").value),variance:Number($("mock-variance").value),observed_at:new Date().toISOString()}; await api("/api/mock/positions",{method:"POST",body:JSON.stringify(body)}); setResult("mock-result",`${body.client_id} → (${body.x}, ${body.y}) を登録しました`); refresh(); } catch(e){setResult("mock-result",e.message,true);} };
$("send-scanning").onclick=async()=>{ try { const now=new Date().toISOString(), client=$("scan-client").value, x=$("scan-x").value, y=$("scan-y").value, floor=$("scan-floor").value; const body={version:"3.0",secret:"test-secret",type:"WiFi",data:{networkId:"L_TEST",observations:[{clientMac:client,locations:[{x:String(x),y:String(y),floorPlanId:floor,floorPlanName:floor,time:now,variance:Number($("scan-variance").value),rssiRecords:[]}],latestRecord:{time:now}}]}}; await api("/api/scanning",{method:"POST",body:JSON.stringify(body)}); setResult("scanning-result",`${client} → (${x}, ${y}) をMeraki位置として送信しました`); refresh(); } catch(e){setResult("scanning-result",e.message,true);} };
document.querySelectorAll(".directions button").forEach(button=>button.onclick=async()=>{ const sessionId=$("movement-session").value; if(!sessionId)return setResult("movement-result","実行中セッションを選択してください",true); const session=latestStatus?.sessions.find(s=>s.session_id===sessionId), sequence=(session?.last_sequence ?? 0)+1; try { await api(`/api/navigation/sessions/${encodeURIComponent(sessionId)}/movements`,{method:"POST",body:JSON.stringify({sequence,distance_m:1,heading_deg:Number(button.dataset.heading),timestamp:new Date().toISOString()})}); setResult("movement-result",`${sessionId}: sequence ${sequence} を送信しました`); refresh(); } catch(e){setResult("movement-result",e.message,true);} });
async function obstacle(blocked){ try { const body={edge_id:$("obstacle-edge").value,blocked,reason:$("obstacle-reason").value||null,source:"dev-panel"}; await api("/api/obstacles",{method:"POST",body:JSON.stringify(body)}); refresh(); } catch(e){$("global-message").textContent=e.message;$("global-message").className="message error";} }
$("block-edge").onclick=()=>obstacle(true); $("unblock-edge").onclick=()=>obstacle(false);
$("sessions").onclick=async event=>{ const button=event.target.closest(".finish-session"); if(!button)return; try{await api(`/api/navigation/sessions/${encodeURIComponent(button.dataset.session)}`,{method:"DELETE"});refresh();}catch(e){$("global-message").textContent=e.message;}};
$("reset-state").onclick=async()=>{ if(!confirm("開発用の現在位置、セッション、通行止め、通信ログをすべて消去しますか？"))return; try{const result=await api("/api/dev/reset",{method:"POST",body:"{}"});latestStatus=null;setResult("mock-result","-");setResult("scanning-result","-");setResult("movement-result","-");$("global-message").textContent=result.message;refresh();}catch(e){$("global-message").textContent=e.message;} };
refresh(); setInterval(refresh,2500);
