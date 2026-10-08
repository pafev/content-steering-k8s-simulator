/* Opt-in experiment: falsify timing only after dash.js reports a real response. */
"use strict";
{
  const params = new URLSearchParams(location.search);
  const target = params.get("attack_cdn");
  const targetReward = Number(params.get("attack_reward"));
  if (
    /^cdn-[123]$/.test(target || "") &&
    params.has("attack_reward") &&
    targetReward > 0 &&
    targetReward < 1
  ) {
    window.__cmcdLieAudit = [];
    window.__cmcdLieEnabled = params.get("attack_enabled") !== "false";
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url, ...args) {
      const endpoint = new URL(url, location.href);
      this.__cmcdLieTarget =
        method.toUpperCase() === "POST" &&
        endpoint.hostname === "telemetry-service.default.svc.cluster.local" &&
        endpoint.pathname === "/v1/cmcd/events";
      return originalOpen.call(this, method, url, ...args);
    };
    XMLHttpRequest.prototype.send = function (body) {
      if (
        !window.__cmcdLieEnabled ||
        !this.__cmcdLieTarget ||
        typeof body !== "string"
      ) {
        return originalSend.call(this, body);
      }
      const altered = body
        .split("\n")
        .map((line) => {
          const url = line.match(/(?:^|,)url="([^"]+)"/)?.[1];
          const status = Number(line.match(/(?:^|,)rc=(\d+)(?=,|$)/)?.[1]);
          const measured = line.match(/(?:^|,)ttlb=(\d+)(?=,|$)/)?.[1];
          const duration = Number(line.match(/(?:^|,)d=(\d+)(?=,|$)/)?.[1]);
          if (
            !url ||
            !measured ||
            !/(?:^|,)e=rr(?:,|$)/.test(line) ||
            !/(?:^|,)ot=v(?:,|$)/.test(line) ||
            !(status >= 200 && status < 300) ||
            !(duration > 0) ||
            new URL(url, location.href).hostname !==
              `${target}.default.svc.cluster.local`
          ) {
            return line;
          }
          const claimed = Math.round(duration * (1 / targetReward - 1) / 5);
          window.__cmcdLieAudit.push({
            url,
            measured_ttlb_ms: Number(measured),
            claimed_ttlb_ms: claimed,
            media_duration_ms: duration,
            claimed_reward: duration / (duration + 5 * claimed),
            sn: Number(line.match(/(?:^|,)sn=(\d+)(?=,|$)/)?.[1]),
          });
          return line.replace(/(^|,)ttlb=\d+(?=,|$)/, `$1ttlb=${claimed}`);
        })
        .join("\n");
      return originalSend.call(this, altered);
    };
  }
}
