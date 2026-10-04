# Current simulator design

This project simulates DASH Content Steering for multiple dash.js clients. Three
CDN caches serve the same media. Clients in one `run_id` share a CSS learning
model; different run IDs have separate models. `fixed` and `random` are
baselines; `ucb1`, `epsilon_greedy`, and `linucb` use CMCD feedback. The CSS
returns an ordered pathway list, and dash.js performs the actual selection and
fallback.

## Learning rule

Each correlated CMCD `e=rr`, `ot=v` report trains the CDN in the reported media
URL once. A successful 2xx video response receives the bounded reward
`d / (d + ttlb)`, with both values in milliseconds. Reported `rc=0` and HTTP
4xx/5xx receive zero. A successful fallback response credits the CDN that
served it. Missing, invalid, or uncorrelated reports do not train. A delayed
report can train while its session and decision still exist.

This reward measures reported video delivery relative to segment duration. It
does not measure viewed quality, stalls, startup delay, or full session QoE.
CMCD and Content Steering do not prescribe this formula. UCB1,
epsilon-greedy, and LinUCB use the same reward; LinUCB additionally uses the
client's buffer level captured at decision time. CDN access logs describe
server traffic and cache behavior but do not train a second time.

The player attaches `cs_decision` to media URLs to correlate responses with CSS
decisions. This is a simulator parameter, not a CMCD field. Run and session
state is temporary in Redis; the runner creates a fresh run ID for each trial
and does not carry learned models between trials. CDN caches are shared across
trials unless explicitly reset.

## Interpreting results

The CSS trusts eligible client reports. A modified player can lie about the
timing of a genuine download and influence the shared model. The optional
attack in [simulations.md](simulations.md) demonstrates this trust assumption;
it does not authenticate the reported measurement. A low CDN reward also does
not identify where along the network path delay occurred.

These are simple cumulative bandit baselines. Network conditions, concurrent
clients, delayed feedback, and cache state can violate assumptions behind
textbook performance guarantees. Compare controlled runs and report observed
behavior, not guaranteed optimality or session QoE.

## References

- [DASH Content Steering, ETSI TS 103 998](https://www.etsi.org/deliver/etsi_ts/103900_103999/103998/01.01.01_60/ts_103998v010101p.pdf): protocol signaling, not a required learning rule.
- [CMCD v2, CTA-5004-B](https://cta-wave.github.io/Resources/common-media-client-data--cta-5004-b.html): client metric and response report definitions.
- [dash.js CMCD documentation](https://dashif.org/dash.js/pages/usage/cmcd.html): player reporting modes.
- [Pytheas, NSDI 2017](https://www.usenix.org/system/files/conference/nsdi17/nsdi17-jiang_0.pdf): multi-client learning for video delivery; not a DASH CSS implementation.
- [Auer et al., 2002](https://doi.org/10.1023/A:1013689704352) and [Li et al., 2010](https://www.schapire.net/papers/www10.pdf): UCB1 and disjoint LinUCB.
