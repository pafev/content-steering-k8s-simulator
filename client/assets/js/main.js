/* Standard dash.js CMCD plus simulator-only run/decision correlation. */
"use strict";
const query = new URLSearchParams(location.search);
const byId = (id) => document.getElementById(id);
const newId = () => crypto.randomUUID();
let player;
let session;
let decisionId = null;
let registrationPending = false;
const pathways = ["cdn-1", "cdn-2", "cdn-3"];

byId("run-id").value = query.get("run_id") || newId();
byId("strategy").value = query.get("strategy") || "ucb1";
byId("manifest").value = query.get("mpd") || "/cdn1/Eldorado/4sec/avc/manifest.mpd";

async function registerSession() {
  if (!session || registrationPending) return;
  registrationPending = true;
  try {
    const response = await fetch("/telemetry/v1/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(session),
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || `Registration failed (${response.status})`);
    }
  } finally {
    registrationPending = false;
  }
}

function setLinks() {
  const url = new URL(location.href);
  url.search = new URLSearchParams({
    run_id: session.run_id, strategy: session.strategy, mpd: session.cid,
  });
  byId("share-link").href = url;
  byId("state-link").href = "/telemetry/v1/state/" + encodeURIComponent(session.run_id);
  history.replaceState(null, "", url);
}

async function load(event) {
  event.preventDefault();
  if (player) player.reset();
  decisionId = null;
  session = {
    run_id: byId("run-id").value,
    strategy: byId("strategy").value,
    sid: newId(),
    cid: new URL(byId("manifest").value, location.href).href,
    seed: 1,
  };
  byId("session-id").textContent = session.sid;
  byId("priority").textContent = "—";
  byId("active-pathway").textContent = "—";
  setLinks();
  byId("status").textContent = "Registering session…";
  try {
    await registerSession();
  } catch (error) {
    byId("status").textContent = error.message + ". Playback has not started; retry Load video.";
    return;
  }
  player = dashjs.MediaPlayer().create();
  player.addRequestInterceptor((request) => {
    const url = new URL(request.url, location.href);
    if (url.origin === location.origin && url.pathname.startsWith("/steering/")) {
      url.searchParams.set("run_id", session.run_id);
      url.searchParams.set("sid", session.sid);
    } else if (url.origin === location.origin && /^\/cdn[123]\//.test(url.pathname) && decisionId) {
      // Kept out of the CDN cache key. CMCD rr includes the actual request URL.
      url.searchParams.set("cs_decision", decisionId);
    }
    request.url = url.href;
    return Promise.resolve(request);
  });
  player.on(dashjs.MediaPlayer.events.CONTENT_STEERING_REQUEST_COMPLETED, (e) => {
    const data = e.currentSteeringResponseData;
    if (!data) return;
    byId("priority").textContent = (data.pathwayPriority || []).join(" → ");
    const base = new URL(e.url || "/steering/manifest.json", location.href);
    const reload = new URL(data.reloadUri || "/steering/manifest.json", base);
    decisionId = reload.searchParams.get("decision_id");
  });
  player.on(dashjs.MediaPlayer.events.FRAGMENT_LOADING_STARTED, (e) => {
    if (e.request?.serviceLocation) {
      byId("active-pathway").textContent = e.request.serviceLocation;
    }
  });
  player.on(dashjs.MediaPlayer.events.ERROR, (e) => {
    byId("status").textContent = "Player: " + (e.error?.message || JSON.stringify(e.error));
  });
  player.initialize(document.querySelector("video"), null, false);
  player.updateSettings({
    streaming: {
      cmcd: {
        enabled: true, applyParametersFromMpd: false,
        version: 2, mode: "header", sid: session.sid, cid: session.cid,
        includeInRequests: ["segment", "mpd"],
        enabledKeys: ["v", "sid", "cid", "ot", "br", "d", "mtp", "bl", "bs", "su"],
        eventTargets: [
          {
            enabled: true, url: location.origin + "/telemetry/v1/cmcd/events",
            events: ["rr"], includeInRequests: ["segment"], batchSize: 1,
            enabledKeys: ["v", "sid", "cid", "e", "ts", "sn", "url", "ot", "rc", "ttfb", "ttlb", "bl"],
          },
          {
            enabled: true, url: location.origin + "/telemetry/v1/cmcd/events",
            events: ["ps", "e"], batchSize: 1,
            enabledKeys: ["v", "sid", "cid", "e", "ts", "sn", "sta", "ec", "msd"],
          },
        ],
      },
    },
  });
  player.attachSource(session.cid);
  byId("status").textContent = "Video loaded. Press play; telemetry is shared with this run.";
}

async function refreshState() {
  if (!session) return;
  try {
    const response = await fetch(byId("state-link").href, { signal: AbortSignal.timeout(4000) });
    if (!response.ok) throw new Error("Telemetry unavailable");
    const state = await response.json();
    const rows = pathways.map((pathway) => {
      const cdn = state.cdn[pathway] || {};
      const model = state.model[pathway] || {};
      const n = Number(model.n || 0);
      const row = document.createElement("tr");
      [pathway, cdn.request_count || 0, cdn.cache_hit_count || 0, n,
        n ? (Number(model.reward_sum) / n).toFixed(3) : "—"].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.appendChild(cell);
      });
      return row;
    });
    byId("pathways").replaceChildren(...rows);
  } catch (error) {
    byId("status").textContent = error.message;
  }
}
byId("playback-form").addEventListener("submit", load);
setInterval(refreshState, 5000);
setInterval(() => registerSession().catch((error) => {
  byId("status").textContent = "Telemetry registration: " + error.message;
}), 30000);
