const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync("client/assets/js/cmcd-lie.js", "utf8");
const report = 'd=4000,e=rr,ot=v,rc=200,sn=1,ttlb=31,url="https://cdn-1.default.svc.cluster.local/seg.m4s"';

function falsify(lambda) {
  class XHR {
    open(method, url) { this.method = method; this.url = url; }
    send(body) { this.body = body; }
  }
  const window = {};
  const context = {
    location: {search: `?attack_cdn=cdn-1&attack_ttlb=800&reward_lambda=${lambda}`,
               href: "http://localhost:8080/"},
    URL, URLSearchParams, XMLHttpRequest: XHR, window,
  };
  vm.runInNewContext(source, context);
  const request = new XHR();
  request.open("POST", "http://telemetry-service.default.svc.cluster.local/v1/cmcd/events");
  request.send(report);
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
