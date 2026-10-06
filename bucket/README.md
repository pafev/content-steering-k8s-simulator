# Media bucket

Place DASH assets here before creating Kind, for example
`Eldorado/4sec/avc/manifest.mpd` and its representation directories.
Only the Caddy origin mounts this read-only backing store; CDNs fill their own
caches over HTTP. Media objects are intentionally ignored by Git.

For each MPD, insert the BaseURLs at MPD level, after ProgramInformation and
before ServiceDescription/Period. Adjust the content directory to the bucket:

```xml
<BaseURL serviceLocation="cdn-1">https://cdn-1.default.svc.cluster.local/Eldorado/4sec/avc/</BaseURL>
<BaseURL serviceLocation="cdn-2">https://cdn-2.default.svc.cluster.local/Eldorado/4sec/avc/</BaseURL>
<BaseURL serviceLocation="cdn-3">https://cdn-3.default.svc.cluster.local/Eldorado/4sec/avc/</BaseURL>
```

Use these direct in-cluster service URLs in the MPD. dash.js intentionally
accepts only the first BaseURL when several relative URLs
occur at the same MPD level; absolute service URLs preserve all three native
steering choices.

Place ContentSteering at MPD level **after Period**, following the
[MPEG schema element order](https://github.com/MPEGGroup/DASHSchema/blob/6th-Ed/DASH-MPD.xsd):

```xml
<ContentSteering queryBeforeStart="true" defaultServiceLocation="cdn-1">http://steering-server.default.svc.cluster.local:30500/manifest.json</ContentSteering>
```

An MPD without ContentSteering can play but will not exercise the CSS.

SegmentTemplate URLs must resolve relative to these BaseURLs; absolute
representation URLs that bypass the CDN services are outside this setup.

Use the same objects and representation layout for all pathways.

The origin and CDN caches serve the MPD without rewriting it.
