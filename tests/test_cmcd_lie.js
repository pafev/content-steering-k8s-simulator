const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync("client/assets/js/cmcd-lie.js", "utf8");
const report = 'd=4000,e=rr,ot=v,rc=200,sn=1,ttlb=31,url="https://cdn-1.default.svc.cluster.local/seg.m4s"';

function falsify(lambda, targets = "cdn-1", body = report, ttlb = 800) {
  class XHR {
    open(method, url) { this.method = method; this.url = url; }
    send(body) { this.body = body; }
  }
  const window = {};
  const context = {
    location: {search: `?attack_cdn=${targets}&attack_ttlb=${ttlb}&reward_lambda=${lambda}`,
               href: "http://localhost:8080/"},
    URL, URLSearchParams, XMLHttpRequest: XHR, window,
  };
  vm.runInNewContext(source, context);
  const request = new XHR();
  request.open("POST", "http://telemetry-service.default.svc.cluster.local/v1/cmcd/events");
  request.send(body);
  return {request, audit: window.__cmcdLieAudit};
}

test("the same forged TTLB reaches telemetry under different reward functions", () => {
  for (const lambda of [1, 5, 15]) {
    const {request, audit} = falsify(lambda);
    assert.match(request.body, /(?:^|,)ttlb=800(?=,|$)/);
    assert.equal(audit[0].claimed_ttlb_ms, 800);
    assert.equal(audit[0].claimed_reward, 4000 / (4000 + lambda * 800));
  }
});

test("forges both alternative CDNs and keeps TTFB within the declared TTLB", () => {
  const lines = ["cdn-1", "cdn-2", "cdn-3"].map((cdn, index) =>
    `d=4000,e=rr,ot=v,rc=200,sn=${index + 1},ttfb=600,ttlb=1500,url="https://${cdn}.default.svc.cluster.local/seg.m4s"`);
  const {request, audit} = falsify(10, "cdn-2,cdn-3", lines.join("\n"), 300);
  const output = request.body.split("\n");
  assert.equal(output[0], lines[0]);
  for (const line of output.slice(1)) {
    assert.match(line, /(?:^|,)ttfb=300(?=,|$)/);
    assert.match(line, /(?:^|,)ttlb=300(?=,|$)/);
  }
  assert.equal(audit.length, 2);
  assert.equal(audit[0].measured_ttfb_ms, 600);
  assert.equal(audit[0].claimed_ttfb_ms, 300);
});
