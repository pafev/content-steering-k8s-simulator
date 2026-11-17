/* Opt-in experiment: falsify timing only after dash.js reports a real response. */
"use strict";
{
  const params = new URLSearchParams(location.search);
  const targets = (params.get("attack_cdn") || "").split(",");
  const targetTtlb = Number(params.get("attack_ttlb"));
  const rewardLambda = Number(params.get("reward_lambda") || 5);
  if (
    targets.length > 0 &&
    new Set(targets).size === targets.length &&
    targets.every((target) => /^cdn-[123]$/.test(target)) &&
    params.has("attack_ttlb") &&
    Number.isSafeInteger(targetTtlb) && targetTtlb > 0 &&
    Number.isFinite(rewardLambda) && rewardLambda > 0
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
          const measuredTtfb = line.match(/(?:^|,)ttfb=(\d+)(?=,|$)/)?.[1];
          const duration = Number(line.match(/(?:^|,)d=(\d+)(?=,|$)/)?.[1]);
          if (
            !url ||
            !measured ||
            !/(?:^|,)e=rr(?:,|$)/.test(line) ||
            !/(?:^|,)ot=v(?:,|$)/.test(line) ||
            !(status >= 200 && status < 300) ||
            !(duration > 0) ||
            !targets.some((target) =>
              new URL(url, location.href).hostname ===
                `${target}.default.svc.cluster.local`)
          ) {
            return line;
          }
          const claimed = targetTtlb;
          const claimedTtfb = measuredTtfb === undefined
            ? undefined : Math.min(Number(measuredTtfb), claimed);
          window.__cmcdLieAudit.push({
            url,
            measured_ttlb_ms: Number(measured),
            claimed_ttlb_ms: claimed,
            measured_ttfb_ms: measuredTtfb === undefined ? null : Number(measuredTtfb),
            claimed_ttfb_ms: claimedTtfb ?? null,
            media_duration_ms: duration,
            claimed_reward: duration / (duration + rewardLambda * claimed),
            sn: Number(line.match(/(?:^|,)sn=(\d+)(?=,|$)/)?.[1]),
          });
          let report = line.replace(/(^|,)ttlb=\d+(?=,|$)/, `$1ttlb=${claimed}`);
          if (measuredTtfb !== undefined && Number(measuredTtfb) > claimed) {
            report = report.replace(/(^|,)ttfb=\d+(?=,|$)/, `$1ttfb=${claimedTtfb}`);
          }
          return report;
        })
        .join("\n");
      return originalSend.call(this, altered);
    };
  }
}
