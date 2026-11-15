/* Standard dash.js CMCD plus simulator-only run/decision correlation. */
"use strict";
const query = new URLSearchParams(location.search);
const byId = (id) => document.getElementById(id);
const newId = () => crypto.randomUUID();
let player;
let session;
let decisionId = null;
let registrationPending = false;
let lastValidPosition = 0;
let playbackStarted = false;
let recoveryTimer = null;
let nativeErrorTimer = null;
let fatalErrorTimer = null;
let recoveryState = "idle";
const fatalRecoveryGraceMs = 3000;
const pathways = ["cdn-1", "cdn-2", "cdn-3"];
const telemetryBase =
  "http://telemetry-service.default.svc.cluster.local:30600";
const steeringHost = "steering-server.default.svc.cluster.local";
const maxVideoKbps = [1500, 3000].includes(Number(query.get("max_video_kbps")))
  ? Number(query.get("max_video_kbps"))
  : 3000;

byId("run-id").value = query.get("run_id") || newId();
byId("strategy").value = query.get("strategy") || "ucb1";
byId("manifest").value =
  query.get("mpd") ||
  "https://cdn-1.default.svc.cluster.local/Eldorado/4sec/avc/manifest.mpd";

async function registerSession() {
  if (!session || registrationPending) return;
  registrationPending = true;
  try {
    const response = await fetch(telemetryBase + "/v1/sessions", {
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
    run_id: session.run_id,
    strategy: session.strategy,
    mpd: session.cid,
    reward_lambda: session.reward_lambda,
    max_video_kbps: maxVideoKbps,
  });
  byId("share-link").href = url;
  byId("state-link").href =
    telemetryBase + "/v1/state/" + encodeURIComponent(session.run_id);
  history.replaceState(null, "", url);
}

async function load(event) {
  event.preventDefault();
  clearTimeout(recoveryTimer);
  clearTimeout(nativeErrorTimer);
  clearTimeout(fatalErrorTimer);
  fatalErrorTimer = null;
  if (player) player.reset();
  decisionId = null;
  recoveryState = "idle";
  lastValidPosition = 0;
  playbackStarted = false;
  session = {
    run_id: byId("run-id").value,
    strategy: byId("strategy").value,
    sid: newId(),
    cid: new URL(byId("manifest").value, location.href).href,
    seed: 1,
    reward_lambda: Number(query.get("reward_lambda") || 5),
  };
  byId("session-id").textContent = session.sid;
  byId("priority").textContent = "—";
  byId("active-pathway").textContent = "—";
  setLinks();
  byId("status").textContent = "Registering session…";
  try {
    await registerSession();
  } catch (error) {
    byId("status").textContent =
      error.message + ". Playback has not started; retry Load video.";
    return;
  }
  createPlayer();
  byId("status").textContent =
    "Video loaded. Press play; telemetry is shared with this run.";
}

function recoveryEvent(type, extra = {}) {
  document.querySelector("video").dispatchEvent(new CustomEvent("player-recovery", {
    detail: { type, sid: session.sid, run_id: session.run_id, ...extra },
  }));
}

function recoverMedia() {
  if (!playbackStarted) return;
  clearTimeout(nativeErrorTimer);
  clearTimeout(fatalErrorTimer);
  fatalErrorTimer = null;
  if (recoveryState !== "idle") {
    if (recoveryState === "succeeded") {
      recoveryState = "exhausted";
      recoveryEvent("recovery_exhausted", { resume_at: lastValidPosition });
    }
    return;
  }
  recoveryState = "pending";
  const video = document.querySelector("video");
  const resumeAt = lastValidPosition;
  recoveryEvent("recovery_attempt", { resume_at: resumeAt });
  byId("status").textContent = `Recovering playback at ${resumeAt.toFixed(2)} s…`;
  const onProgress = () => {
    if (recoveryState !== "pending" || video.seeking || video.paused || video.error ||
        video.currentTime <= resumeAt + 0.25) return;
    recoveryState = "succeeded";
    clearTimeout(recoveryTimer);
    video.removeEventListener("timeupdate", onProgress);
    recoveryEvent("recovery_success", { resume_at: resumeAt,
      resumed_at: video.currentTime });
    byId("status").textContent = "Playback recovered.";
  };
  const fail = (reason) => {
    if (recoveryState !== "pending") return;
    recoveryState = "failed";
    clearTimeout(recoveryTimer);
    video.removeEventListener("timeupdate", onProgress);
    recoveryEvent("recovery_failure", { resume_at: resumeAt, reason });
    byId("status").textContent = "Playback recovery failed: " + reason;
  };
  video.addEventListener("timeupdate", onProgress);
  recoveryTimer = setTimeout(() => fail("no media progress within 20 seconds"), 20000);
  try {
    player.reset();
    decisionId = null;
    createPlayer(resumeAt, fail);
  } catch (error) {
    fail(error.message);
  }
}

function waitBeforeRecovery() {
  if (!playbackStarted || fatalErrorTimer !== null) return;
  const positionAtError = lastValidPosition;
  recoveryEvent("recovery_wait", { resume_at: positionAtError,
    grace_ms: fatalRecoveryGraceMs });
  byId("status").textContent = "Media error; checking playback before recovery…";
  fatalErrorTimer = setTimeout(() => {
    fatalErrorTimer = null;
    const video = document.querySelector("video");
    if (!video.error && !video.paused &&
        video.currentTime > positionAtError + 0.25) {
      recoveryEvent("recovery_cancelled", { resume_at: positionAtError });
      return;
    }
    recoverMedia();
  }, fatalRecoveryGraceMs);
}

function createPlayer(resumeAt = null, recoveryFailed = null) {
  const video = document.querySelector("video");
  const contentId = new URL(session.cid).pathname;
  player = dashjs.MediaPlayer().create();
  // The research runner may attach playback event instrumentation.
  window.__viewerTap?.(player);
  player.addRequestInterceptor((request) => {
    const url = new URL(request.url, location.href);
    if (url.hostname === steeringHost && url.pathname === "/manifest.json") {
      url.searchParams.set("run_id", session.run_id);
      url.searchParams.set("sid", session.sid);
    } else if (
      /^cdn-[123]\.default\.svc\.cluster\.local$/.test(url.hostname) &&
      decisionId
    ) {
      // Kept out of the CDN cache key. CMCD rr includes the actual request URL.
      url.searchParams.set("cs_decision", decisionId);
    }
    request.url = url.href;
    return Promise.resolve(request);
  });
  player.on(
    dashjs.MediaPlayer.events.CONTENT_STEERING_REQUEST_COMPLETED,
    (e) => {
      const data = e.currentSteeringResponseData;
      if (!data) return;
      byId("priority").textContent = (data.pathwayPriority || []).join(" → ");
      const base = new URL(
        e.url || "http://" + steeringHost + ":30500/manifest.json",
      );
      const reload = new URL(data.reloadUri || "/manifest.json", base);
      decisionId = reload.searchParams.get("decision_id");
    },
  );
  player.on(dashjs.MediaPlayer.events.FRAGMENT_LOADING_STARTED, (e) => {
    if (e.request?.serviceLocation) {
      byId("active-pathway").textContent = e.request.serviceLocation;
    }
  });
  player.on(dashjs.MediaPlayer.events.ERROR, (e) => {
    byId("status").textContent =
      "Player: " + (e.error?.message || JSON.stringify(e.error));
    if (playbackStarted && ([2, 3, 4].includes(Number(e.error?.code)) ||
        /MEDIA_ERR_(NETWORK|DECODE|SRC_NOT_SUPPORTED)/.test(e.error?.message || ""))) {
      // dash.js emits ERROR only after its own media recovery is exhausted.
      waitBeforeRecovery();
    }
  });
  if (resumeAt !== null) {
    let resumeRequested = false;
    player.on(dashjs.MediaPlayer.events.STREAM_INITIALIZED, () => {
      if (resumeRequested) return;
      resumeRequested = true;
      try {
        player.seek(resumeAt);
        Promise.resolve(video.play()).catch((error) => recoveryFailed(error.message));
      } catch (error) {
        recoveryFailed(error.message);
      }
    });
  }
  player.initialize(video, null, false);
  player.updateSettings({
    streaming: {
      cmcd: {
        enabled: true,
        applyParametersFromMpd: false,
        version: 2,
        mode: "header",
        sid: session.sid,
        cid: contentId,
        includeInRequests: ["segment", "mpd"],
        enabledKeys: [
          "v",
          "sid",
          "cid",
          "ot",
          "br",
          "d",
          "mtp",
          "bl",
          "bs",
          "su",
        ],
        eventTargets: [
          {
            enabled: true,
            url: telemetryBase + "/v1/cmcd/events",
            events: ["rr"],
            includeInRequests: ["segment"],
            batchSize: 1,
            enabledKeys: [
              "v",
              "sid",
              "cid",
              "e",
              "ts",
              "sn",
              "url",
              "ot",
              "rc",
              "ttfb",
              "ttlb",
              "d",
              "bl",
            ],
          },
          {
            enabled: true,
            url: telemetryBase + "/v1/cmcd/events",
            events: ["e"],
            batchSize: 1,
            enabledKeys: ["v", "sid", "cid", "e", "ts", "sn", "sta", "ec"],
          },
        ],
      },
      abr: { maxBitrate: { video: maxVideoKbps } },
    },
  });
  player.attachSource(session.cid);
}

async function refreshState() {
  if (!session) return;
  try {
    const response = await fetch(byId("state-link").href, {
      signal: AbortSignal.timeout(4000),
    });
    if (!response.ok) throw new Error("Telemetry unavailable");
    const state = await response.json();
    const rows = pathways.map((pathway) => {
      const cdn = state.cdn[pathway] || {};
      const model = state.model[pathway] || {};
      const n = Number(model.n || 0);
      const row = document.createElement("tr");
      [
        pathway,
        cdn.request_count || 0,
        cdn.cache_hit_count || 0,
        n,
        n ? (Number(model.reward_sum) / n).toFixed(3) : "—",
      ].forEach((value) => {
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
const playbackVideo = document.querySelector("video");
playbackVideo.addEventListener("playing", () => { playbackStarted = true; });
playbackVideo.addEventListener("timeupdate", () => {
  if (Number.isFinite(playbackVideo.currentTime) && playbackVideo.currentTime > 0 && !playbackVideo.error)
    lastValidPosition = playbackVideo.currentTime;
});
playbackVideo.addEventListener("error", () => {
  if (!playbackStarted) return;
  clearTimeout(nativeErrorTimer);
  const positionAtError = lastValidPosition;
  nativeErrorTimer = setTimeout(() => {
    if (playbackVideo.error && playbackVideo.currentTime <= positionAtError + 0.05)
      recoverMedia();
  }, 5000);
});
setInterval(refreshState, 5000);
setInterval(
  () =>
    registerSession().catch((error) => {
      byId("status").textContent = "Telemetry registration: " + error.message;
    }),
  30000,
);
