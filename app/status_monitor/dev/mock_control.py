"""Web-based control panel for the mock server.

Provides buttons/sliders to adjust detector count, loading state, and
eviction threshold. Writes state to /tmp/mock-state.json which the
mock server reads on each request.

Usage:
    python mock_control.py    # opens on :3002
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PORT = 3002
STATE_FILE = "/tmp/mock-state.json"


def read_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return {"num_detectors": 3, "loading": False, "eviction": 75, "synthetic": True}


def write_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


HTML = """<!DOCTYPE html>
<html>
<head>
<title>Mock Control</title>
<style>
  body { font-family: system-ui; background: #1a1a2e; color: #eee; display: flex;
         flex-direction: column; align-items: center; justify-content: center;
         min-height: 100vh; margin: 0; gap: 24px; }
  h2 { margin: 0; }
  .control { display: flex; align-items: center; gap: 16px; font-size: 1.1em; }
  .num { font-size: 2em; font-weight: bold; min-width: 60px; text-align: center;
         color: #e94560; }
  .pm { font-size: 1.5em; width: 48px; height: 48px; border: none; border-radius: 8px;
        cursor: pointer; background: #16213e; color: #eee; transition: background 0.15s; }
  .pm:hover { background: #0f3460; }
  .toggle { display: flex; align-items: center; gap: 12px; }
  .switch { position: relative; width: 56px; height: 30px; cursor: pointer; }
  .switch input { opacity: 0; width: 0; height: 0; }
  .slider { position: absolute; inset: 0; background: #333; border-radius: 15px;
            transition: background 0.2s; }
  .slider::before { content: ''; position: absolute; width: 24px; height: 24px;
                    left: 3px; top: 3px; background: #eee; border-radius: 50%;
                    transition: transform 0.2s; }
  .switch input:checked + .slider { background: #e94560; }
  .switch input:checked + .slider::before { transform: translateX(26px); }
  .seg-toggle { display: flex; border-radius: 8px; overflow: hidden; border: 2px solid #16213e; }
  .seg-btn { padding: 8px 20px; border: none; cursor: pointer; font-size: 1em;
             font-weight: 600; transition: background 0.2s, color 0.2s;
             background: #16213e; color: #666; }
  .seg-btn.active-synth { background: #e94560; color: #fff; }
  .seg-btn.active-live { background: #2ecc71; color: #fff; }
  .json-section { width: 90%; max-width: 700px; }
  .json-section h3 { margin: 0 0 8px; font-size: 0.95em; color: #aaa; }
  .json-header { display: flex; justify-content: space-between; align-items: center; }
  .json-tabs { display: flex; gap: 4px; }
  .json-tab { background: #16213e; color: #aaa; border: none; padding: 4px 12px;
              border-radius: 6px 6px 0 0; cursor: pointer; font-size: 0.85em; }
  .json-tab.active { background: #0d1b2a; color: #eee; }
  .copy-btn { background: #16213e; color: #aaa; border: none; padding: 4px 12px;
              border-radius: 6px; cursor: pointer; font-size: 0.8em; transition: color 0.2s; }
  .copy-btn:hover { color: #eee; }
  .json-box { background: #0d1b2a; border-radius: 0 0 8px 8px; padding: 16px;
              overflow-x: auto; font-size: 0.8em; line-height: 1.5; max-height: 400px;
              overflow-y: auto; }
  .json-box pre { margin: 0; white-space: pre-wrap; word-break: break-word; }
  .json-str { color: #a8db8f; } .json-num { color: #d19a66; }
  .json-bool { color: #56b6c2; } .json-null { color: #888; }
  .json-key { color: #e06c75; }
</style>
</head>
<body>
  <h2>Mock Data Control</h2>
  <div class="seg-toggle">
    <button class="seg-btn active-synth" id="btnSynthetic" onclick="setDataMode(true)">Synthetic Data</button>
    <button class="seg-btn" id="btnLive" onclick="setDataMode(false)">Live Data</button>
  </div>
  <div class="control synthetic-control">
    <span>Detectors:</span>
    <button class="pm" onclick="adjust(-1)">-</button>
    <span class="num" id="num">3</span>
    <button class="pm" onclick="adjust(1)">+</button>
  </div>
  <div class="toggle synthetic-control">
    <span>Loading Detector Models:</span>
    <label class="switch">
      <input type="checkbox" id="loading" onchange="toggleLoading()">
      <span class="slider"></span>
    </label>
    <span id="loadLabel">OFF</span>
  </div>
  <div class="control synthetic-control">
    <span>Eviction Threshold:</span>
    <input type="range" id="eviction" min="0" max="100" value="75"
           style="width:200px; accent-color:#e94560;" oninput="setEviction(this.value)">
    <span class="num" id="evictionVal" style="font-size:1.5em; min-width:50px;">75%</span>
  </div>
  <div class="json-section">
    <div class="json-header">
      <div class="json-tabs">
        <button class="json-tab active" data-tab="resources" onclick="switchTab('resources')">resources.json</button>
        <button class="json-tab" data-tab="metrics" onclick="switchTab('metrics')">metrics.json</button>
      </div>
      <button class="copy-btn" id="copyBtn" onclick="copyJson()">Copy</button>
    </div>
    <div class="json-box">
      <pre id="jsonPreview">Loading...</pre>
      <textarea id="jsonRaw" style="display:none;"></textarea>
    </div>
  </div>
  <script>
    let current = 3;
    let synthetic = true;
    function sendState() {
      const loading = document.getElementById('loading').checked;
      const eviction = document.getElementById('eviction').value;
      return fetch('/set?num_detectors=' + current + '&loading=' + (loading ? '1' : '0') + '&eviction=' + eviction + '&synthetic=' + (synthetic ? '1' : '0'),
                   { method: 'POST' });
    }
    async function setDataMode(isSynthetic) {
      synthetic = isSynthetic;
      updateDataModeUI();
      await sendState();
    }
    function updateDataModeUI() {
      document.getElementById('btnSynthetic').className = 'seg-btn' + (synthetic ? ' active-synth' : '');
      document.getElementById('btnLive').className = 'seg-btn' + (synthetic ? '' : ' active-live');
      const opacity = synthetic ? '1' : '0.4';
      for (const el of document.querySelectorAll('.synthetic-control')) {
        el.style.opacity = opacity;
        el.style.pointerEvents = synthetic ? 'auto' : 'none';
      }
    }
    async function adjust(delta) {
      current = Math.max(0, Math.min(29, current + delta));
      document.getElementById('num').textContent = current;
      await sendState();
    }
    async function toggleLoading() {
      document.getElementById('loadLabel').textContent =
        document.getElementById('loading').checked ? 'ON' : 'OFF';
      await sendState();
    }
    async function setEviction(val) {
      document.getElementById('evictionVal').textContent = val + '%';
      await sendState();
    }
    async function refresh() {
      const r = await fetch('/current');
      const data = await r.json();
      current = data.num_detectors;
      document.getElementById('num').textContent = current;
      document.getElementById('loading').checked = data.loading;
      document.getElementById('loadLabel').textContent = data.loading ? 'ON' : 'OFF';
      const ev = data.eviction ?? 75;
      document.getElementById('eviction').value = ev;
      document.getElementById('evictionVal').textContent = ev + '%';
      synthetic = data.synthetic ?? true;
      updateDataModeUI();
    }
    let activeTab = 'resources';
    function switchTab(tab) {
      activeTab = tab;
      document.querySelectorAll('.json-tab').forEach(el =>
        el.classList.toggle('active', el.dataset.tab === tab));
      refreshJson();
    }
    function syntaxHighlight(json) {
      return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
        function (match) {
          let cls = 'json-num';
          if (/^"/.test(match)) {
            cls = /:$/.test(match) ? 'json-key' : 'json-str';
          } else if (/true|false/.test(match)) {
            cls = 'json-bool';
          } else if (/null/.test(match)) {
            cls = 'json-null';
          }
          return '<span class="' + cls + '">' + match + '</span>';
        });
    }
    async function refreshJson() {
      try {
        const url = activeTab === 'resources'
          ? 'http://localhost:3001/status/resources.json'
          : 'http://localhost:3001/status/metrics.json';
        const r = await fetch(url);
        const data = await r.json();
        const pretty = JSON.stringify(data, null, 2);
        document.getElementById('jsonPreview').innerHTML = syntaxHighlight(pretty);
        document.getElementById('jsonRaw').value = pretty;
      } catch (e) {
        document.getElementById('jsonPreview').textContent = 'Error: ' + e.message;
      }
    }
    function copyJson() {
      const text = document.getElementById('jsonRaw').value;
      navigator.clipboard.writeText(text).then(() => {
        const btn = document.getElementById('copyBtn');
        btn.textContent = 'Copied!';
        setTimeout(() => btn.textContent = 'Copy', 1500);
      });
    }
    // Re-fetch JSON after every state change
    const origSendState = sendState;
    sendState = async function() {
      await origSendState();
      setTimeout(refreshJson, 200);
    };
    refresh();
    refreshJson();
  </script>
</body>
</html>"""


class ControlHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/current":
            body = json.dumps(read_state()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML.encode())

    def do_POST(self):
        if self.path.startswith("/set"):
            params = parse_qs(urlparse(self.path).query)
            state = read_state()
            if "num_detectors" in params:
                state["num_detectors"] = max(0, min(int(params["num_detectors"][0]), 29))
            if "loading" in params:
                state["loading"] = params["loading"][0] == "1"
            if "eviction" in params:
                state["eviction"] = max(0, min(100, int(params["eviction"][0])))
            if "synthetic" in params:
                state["synthetic"] = params["synthetic"][0] == "1"
            write_state(state)
            mode = "synthetic" if state.get("synthetic", True) else "real"
            print(f"[control] {mode}, {state['num_detectors']} detectors, loading={state['loading']}, eviction={state.get('eviction', 75)}")
            self.send_response(200)
            self.end_headers()
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    print(f"Mock control panel on http://localhost:{PORT}")
    HTTPServer(("", PORT), ControlHandler).serve_forever()
