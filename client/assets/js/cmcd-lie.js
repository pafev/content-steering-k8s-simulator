/* Opt-in experiment: falsify timing only after dash.js reports a real response. */
"use strict";
{
  const params = new URLSearchParams(location.search);
  const target = params.get("attack_cdn");
  const claimedTtlb = Number(params.get("attack_ttlb_ms"));
  if (/^cdn-[123]$/.test(target || "") && Number.isFinite(claimedTtlb) && claimedTtlb > 0) {
    window.__cmcdLieAudit = [];
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url, ...args) {
      const endpoint = new URL(url, location.href);
      this.__cmcdLieTarget = method.toUpperCase() === "POST" &&
        endpoint.origin === location.origin && endpoint.pathname === "/telemetry/v1/cmcd/events";
      return originalOpen.call(this, method, url, ...args);
    };
    XMLHttpRequest.prototype.send = function (body) {
      if (!this.__cmcdLieTarget || typeof body !== "string") {
        return originalSend.call(this, body);
      }
      const altered = body.split("\n").map((line) => {
        const url = line.match(/(?:^|,)url="([^"]+)"/)?.[1];
        const status = Number(line.match(/(?:^|,)rc=(\d+)(?=,|$)/)?.[1]);
        const measured = line.match(/(?:^|,)ttlb=(\d+)(?=,|$)/)?.[1];
        if (!url || !measured || !/(?:^|,)e=rr(?:,|$)/.test(line) ||
            !/(?:^|,)ot=v(?:,|$)/.test(line) || !(status >= 200 && status < 300) ||
            !new URL(url, location.href).pathname.startsWith(`/cdn${target.at(-1)}/`)) {
          return line;
        }
        window.__cmcdLieAudit.push({ url, measured_ttlb_ms: Number(measured),
          claimed_ttlb_ms: claimedTtlb, sn: Number(line.match(/(?:^|,)sn=(\d+)(?=,|$)/)?.[1]) });
        return line.replace(/(^|,)ttlb=\d+(?=,|$)/, `$1ttlb=${claimedTtlb}`);
      }).join("\n");
      return originalSend.call(this, altered);
    };
  }
}
