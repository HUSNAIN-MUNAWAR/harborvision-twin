from __future__ import annotations

import base64
import os
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
LOCAL_API = os.environ.get("HARBORVISION_LOCAL_API", "http://127.0.0.1:8000")

BRIDGE_JS = r"""
window.__hvMemory = {};
window.__hvStorage = {
  getItem: (key) => Object.prototype.hasOwnProperty.call(window.__hvMemory, key) ? window.__hvMemory[key] : null,
  setItem: (key, value) => { window.__hvMemory[key] = String(value); },
  removeItem: (key) => { delete window.__hvMemory[key]; }
};
window.fetch = async function(url, options = {}) {
  const headers = options.headers || {};
  const result = await window.__harborApiBridge(String(url), options.method || 'GET', headers, options.body || null);
  const binary = atob(result.body_b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Response(bytes, {status: result.status, headers: result.headers});
};
class HarborEventSource {
  constructor(url) {
    this.url = url; this.readyState = 1; this.listeners = {};
    setTimeout(() => { if (this.onopen) this.onopen({type:'open'}); }, 40);
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  close() { this.readyState = 2; }
}
window.EventSource = HarborEventSource;
"""


def build_embedded_html() -> str:
    html = (ROOT / "apps" / "web" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "apps" / "web" / "styles.css").read_text(encoding="utf-8")
    js = (ROOT / "apps" / "web" / "app.js").read_text(encoding="utf-8").replace("localStorage.", "window.__hvStorage.")
    html = html.replace('<link rel="stylesheet" href="/assets/styles.css" />', f"<style>{css}</style>")
    html = html.replace('<script type="module" src="/assets/app.js"></script>', f"<script>{BRIDGE_JS}</script><script>{js}</script>")
    return html


def api_bridge(url: str, method: str, headers: dict, body: str | None) -> dict:
    parsed = urlparse(url)
    path = parsed.path if parsed.scheme else url.split("?", 1)[0]
    query = parsed.query if parsed.scheme else (url.split("?", 1)[1] if "?" in url else "")
    target = f"{LOCAL_API}{path}{'?' + query if query else ''}"
    forwarded_headers = {
        str(k): str(v) for k, v in dict(headers).items() if str(k).lower() not in {"host", "content-length", "accept-encoding"}
    }
    response = requests.request(method, target, headers=forwarded_headers, data=body, timeout=180)
    clean_headers = {
        k: v
        for k, v in response.headers.items()
        if k.lower() not in {"content-encoding", "transfer-encoding", "content-length", "connection"}
    }
    return {
        "status": response.status_code,
        "headers": clean_headers,
        "body_b64": base64.b64encode(response.content).decode("ascii"),
    }
