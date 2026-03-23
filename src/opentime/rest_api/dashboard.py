"""Self-contained HTML dashboard for OpenTime."""

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenTime Dashboard</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --border: #2a2d3a;
    --text: #e1e4ed;
    --muted: #8b8fa3;
    --accent: #6c7eff;
    --accent-dim: #4a5099;
    --green: #4ade80;
    --yellow: #facc15;
    --red: #f87171;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg); color: var(--text); padding: 24px; line-height: 1.5;
  }
  .header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 24px; flex-wrap: wrap; gap: 12px;
  }
  .header h1 { font-size: 24px; font-weight: 600; }
  .header h1 span { color: var(--accent); }
  .header-right { display: flex; align-items: center; gap: 16px; }
  .clock { color: var(--muted); font-size: 14px; font-family: monospace; }
  select {
    background: var(--surface); color: var(--text); border: 1px solid var(--border);
    padding: 6px 12px; border-radius: 6px; font-size: 14px; cursor: pointer;
  }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }
  @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 20px;
  }
  .card h2 {
    font-size: 14px; text-transform: uppercase; letter-spacing: 1px;
    color: var(--muted); margin-bottom: 16px;
  }
  .stat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
  .stat-card {
    background: var(--bg); border-radius: 8px; padding: 14px;
  }
  .stat-card .label { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
  .stat-card .task-type { font-size: 15px; font-weight: 600; margin-bottom: 8px; color: var(--accent); }
  .stat-card .values { font-size: 12px; color: var(--muted); line-height: 1.8; }
  .stat-card .values b { color: var(--text); font-weight: 500; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--muted); font-weight: 500; padding: 8px 12px;
       border-bottom: 1px solid var(--border); font-size: 12px; text-transform: uppercase; }
  td { padding: 8px 12px; border-bottom: 1px solid var(--border); }
  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 11px; font-weight: 500;
  }
  .badge-active { background: rgba(74, 222, 128, 0.15); color: var(--green); }
  .badge-start { background: rgba(108, 126, 255, 0.15); color: var(--accent); }
  .badge-end { background: rgba(139, 143, 163, 0.15); color: var(--muted); }
  .badge-stop { background: rgba(250, 204, 21, 0.15); color: var(--yellow); }
  .empty { color: var(--muted); font-style: italic; padding: 20px 0; text-align: center; }
  .scroll-table { max-height: 400px; overflow-y: auto; }
  .full-width { grid-column: 1 / -1; }
</style>
</head>
<body>

<div class="header">
  <h1><span>Open</span>Time</h1>
  <div class="header-right">
    <div class="clock" id="clock">--</div>
    <select id="agent-select"><option value="*">All Agents</option></select>
  </div>
</div>

<div class="grid">

  <div class="card">
    <h2>Active Tasks</h2>
    <div id="active-tasks"><div class="empty">No active tasks</div></div>
  </div>

  <div class="card">
    <h2>Agents</h2>
    <div id="agents-list"><div class="empty">Loading...</div></div>
  </div>

  <div class="card full-width">
    <h2>Duration Statistics</h2>
    <div class="stat-grid" id="stats"><div class="empty">No data yet</div></div>
  </div>

  <div class="card full-width">
    <h2>Recent Events</h2>
    <div class="scroll-table" id="events"><div class="empty">No events</div></div>
  </div>

</div>

<script>
const $ = (id) => document.getElementById(id);
let currentAgent = '*';

function fmt(seconds) {
  if (seconds < 1) return seconds.toFixed(3) + 's';
  if (seconds < 60) return seconds.toFixed(1) + 's';
  if (seconds < 3600) return (seconds / 60).toFixed(1) + 'm';
  return (seconds / 3600).toFixed(1) + 'h';
}

function badge(type) {
  const cls = {
    task_start: 'badge-start', task_end: 'badge-end',
    agent_stop: 'badge-stop'
  }[type] || 'badge-start';
  return `<span class="badge ${cls}">${type}</span>`;
}

function agentParam() {
  return currentAgent === '*' ? 'agent_id=*' : `agent_id=${encodeURIComponent(currentAgent)}`;
}

function headers() {
  const h = {};
  if (currentAgent !== '*') h['X-Agent-ID'] = currentAgent;
  return h;
}

async function api(path) {
  try {
    const resp = await fetch(path, { headers: headers() });
    if (!resp.ok) return null;
    return await resp.json();
  } catch { return null; }
}

function tickClock() {
  const now = new Date();
  const utc = now.toISOString().replace('T', ' ').slice(0, 19);
  const local = now.toLocaleTimeString('en-US', {
    hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true
  });
  $('clock').textContent = utc + ' UTC  |  ' + local;
}
tickClock();
setInterval(tickClock, 1000);

async function refreshAgents() {
  const data = await api('/agents');
  if (!data) return;
  const sel = $('agent-select');
  const prev = sel.value;
  sel.innerHTML = '<option value="*">All Agents</option>';
  for (const a of data.agents) {
    sel.innerHTML += `<option value="${a}" ${a === prev ? 'selected' : ''}>${a}</option>`;
  }
  $('agents-list').innerHTML = data.agents.length
    ? data.agents.map(a => `<div style="padding:4px 0;font-size:14px;">${a}</div>`).join('')
    : '<div class="empty">No agents</div>';
}

async function refreshActive() {
  const data = await api(`/events/active?${agentParam()}`);
  const el = $('active-tasks');
  if (!data || !data.active_tasks.length) {
    el.innerHTML = '<div class="empty">No active tasks</div>';
    return;
  }
  let html = '<table><tr><th>Task Type</th><th>Agent</th><th>Started</th><th>Correlation ID</th></tr>';
  for (const t of data.active_tasks) {
    const time = t.timestamp.replace('T', ' ').slice(0, 19);
    html += `<tr><td>${t.task_type || '-'}</td><td>${t.correlation_id ? '' : '-'}</td>`;
    const cid = (t.correlation_id || '-').slice(0, 12);
    html += `<td>${time}</td><td style="font-family:monospace;font-size:11px">${cid}...</td></tr>`;
  }
  el.innerHTML = html + '</table>';
}

async function refreshStats() {
  const data = await api(`/stats/durations?${agentParam()}`);
  const el = $('stats');
  if (!data || !data.summaries.length) {
    el.innerHTML = '<div class="empty">No duration data yet. Start and end some tasks to see statistics.</div>';
    return;
  }
  el.innerHTML = data.summaries.map(s => `
    <div class="stat-card">
      <div class="task-type">${s.task_type}</div>
      <div class="values">
        <b>${s.count}</b> completed<br>
        Mean: <b>${fmt(s.mean_seconds)}</b> &middot;
        Median: <b>${fmt(s.median_seconds)}</b><br>
        P95: <b>${fmt(s.p95_seconds)}</b> &middot;
        Range: <b>${fmt(s.min_seconds)}</b> - <b>${fmt(s.max_seconds)}</b>
      </div>
    </div>
  `).join('');
}

async function refreshEvents() {
  const data = await api(`/events?limit=50&${agentParam().replace('agent_id=*', '')}`);
  const el = $('events');
  if (!data || !data.events.length) {
    el.innerHTML = '<div class="empty">No events recorded yet.</div>';
    return;
  }
  let html = '<table><tr><th>Time</th><th>Type</th><th>Task</th><th>Agent</th></tr>';
  for (const e of data.events) {
    const time = e.timestamp.replace('T', ' ').slice(11, 19);
    html += `<tr><td style="font-family:monospace">${time}</td>`;
    html += `<td>${badge(e.event_type)}</td>`;
    html += `<td>${e.task_type || '-'}</td>`;
    const eid = e.correlation_id ? e.correlation_id.slice(0, 8) : '-';
    html += `<td style="font-size:12px;color:var(--muted)">${eid}</td></tr>`;
  }
  el.innerHTML = html + '</table>';
}

async function refreshAll() {
  await Promise.all([refreshAgents(), refreshActive(), refreshStats(), refreshEvents()]);
}

$('agent-select').addEventListener('change', (e) => {
  currentAgent = e.target.value;
  refreshAll();
});

refreshAll();
setInterval(refreshActive, 5000);
setInterval(() => { refreshStats(); refreshEvents(); refreshAgents(); }, 30000);
</script>
</body>
</html>
"""
