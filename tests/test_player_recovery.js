const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("client/assets/js/main.js", "utf8");
const listeners = {};
const video = {
  currentTime: 0, paused: false, seeking: false, error: null,
  addEventListener(name, callback) { (listeners[name] ||= []).push(callback); },
  removeEventListener(name, callback) {
    listeners[name] = (listeners[name] || []).filter((item) => item !== callback);
  },
  dispatchEvent(event) {
    for (const callback of [...(listeners[event.type] || [])]) callback(event);
  },
  play() { return Promise.resolve(); },
};
const elements = Object.fromEntries(
  ["run-id", "strategy", "manifest", "session-id", "priority", "active-pathway",
   "status", "share-link", "state-link", "playback-form"].map((id) =>
    [id, { value: "", textContent: "", href: "", addEventListener() {} }]),
);
const players = [];
const timers = [];
const eventNames = { CONTENT_STEERING_REQUEST_COMPLETED: "steering",
  FRAGMENT_LOADING_STARTED: "fragment", ERROR: "error", STREAM_INITIALIZED: "stream" };
const context = {
  URL, URLSearchParams, Promise, Number, JSON,
  location: { search: "?run_id=test-run&reward_lambda=10", href: "http://localhost/" },
  history: { replaceState() {} },
  crypto: { randomUUID: () => "same-sid" },
  document: { getElementById: (id) => elements[id], querySelector: () => video },
  CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
  dashjs: { MediaPlayer: Object.assign(() => ({ create() {
    const p = { handlers: {}, resetCount: 0, interceptors: [],
      reset() { this.resetCount++; },
      addRequestInterceptor(fn) { this.interceptors.push(fn); },
      on(name, fn) { this.handlers[name] = fn; },
      initialize() {}, updateSettings(settings) { this.settings = settings; },
      attachSource(url) { this.source = url; }, seek(time) { this.seekTo = time; },
    };
    players.push(p);
    return p;
  } }), { events: eventNames }) },
  fetch: async () => ({ ok: true }),
  AbortSignal: { timeout: () => null },
  setInterval() {}, setTimeout: (fn, delay) => {
    timers.push({ fn, delay });
    if (delay === 0) queueMicrotask(fn);
    return 1;
  }, clearTimeout() {},
};
vm.createContext(context);
context.window = context;
vm.runInContext(source, context);
const recovered = [];
video.addEventListener("player-recovery", (event) => recovered.push(event.detail));

(async () => {
  await vm.runInContext("load({preventDefault(){}})", context);
  assert.equal(players.length, 1);
  context.__cmcdLieEnabled = true;
  video.dispatchEvent({ type: "playing" });
  video.currentTime = 12.5;
  video.dispatchEvent({ type: "timeupdate" });
  video.error = { code: 3 };
  video.dispatchEvent({ type: "error" });
  assert.equal(players.length, 1);
  video.error = null;
  timers.at(-1).fn();
  assert.equal(players.length, 1);
  video.dispatchEvent({ type: "waiting" });
  video.dispatchEvent({ type: "stalled" });
  assert.equal(players.length, 1);
  players[0].handlers.error({ error: { code: 3, message: "MEDIA_ERR_DECODE" } });
  assert.equal(timers.at(-1).delay, 3000);
  video.currentTime = 13;
  video.dispatchEvent({ type: "timeupdate" });
  timers.at(-1).fn();
  assert.equal(players.length, 1);
  assert.equal(recovered.at(-1).type, "recovery_cancelled");
  video.error = { code: 3 };
  video.dispatchEvent({ type: "error" });
  players[0].handlers.error({ error: { code: 3, message: "MEDIA_ERR_DECODE" } });
  assert.equal(players.length, 1);
  assert.equal(timers.at(-1).delay, 3000);
  timers.at(-1).fn();
  assert.equal(players.length, 2);
  assert.equal(players[0].resetCount, 1);
  const attempt = recovered.find((event) => event.type === "recovery_attempt");
  assert.equal(attempt.resume_at, 13);
  assert.equal(attempt.sid, "same-sid");
  assert.equal(attempt.run_id, "test-run");
  assert.equal(players[1].settings.streaming.cmcd.sid, "same-sid");
  assert.equal(context.__cmcdLieEnabled, true);
  assert.equal(players[1].settings.streaming.cmcd.eventTargets[0].events[0], "rr");
  const steeringRequest = await players[1].interceptors[0]({
    url: "http://steering-server.default.svc.cluster.local:30500/manifest.json",
  });
  assert.equal(new URL(steeringRequest.url).searchParams.get("sid"), "same-sid");
  assert.equal(new URL(steeringRequest.url).searchParams.get("run_id"), "test-run");
  players[1].handlers.stream();
  assert.equal(players[1].seekTo, 13);
  video.error = null;
  video.currentTime = 13.3;
  video.dispatchEvent({ type: "timeupdate" });
  assert.equal(recovered.at(-1).type, "recovery_success");
  video.error = { code: 3 };
  video.dispatchEvent({ type: "error" });
  players[1].handlers.error({ error: { code: 3, message: "MEDIA_ERR_DECODE" } });
  assert.equal(players.length, 2);
  timers.at(-1).fn();
  assert.equal(players.length, 2);
  assert.equal(recovered.at(-1).type, "recovery_exhausted");
})().catch((error) => { console.error(error); process.exitCode = 1; });
