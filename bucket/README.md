# Media bucket

Place DASH assets here before creating Kind, for example
`Eldorado/4sec/avc/manifest.mpd` and its representation directories.
Only the Caddy origin mounts this read-only backing store; CDNs fill their own
caches over HTTP. Media objects are intentionally ignored by Git.

For each MPD, insert the BaseURLs at MPD level, after ProgramInformation and
before ServiceDescription/Period. Adjust the content directory to the bucket:

```xml
<BaseURL serviceLocation="cdn-1">http://content-steering.invalid/cdn1/Eldorado/4sec/avc/</BaseURL>
<BaseURL serviceLocation="cdn-2">http://content-steering.invalid/cdn2/Eldorado/4sec/avc/</BaseURL>
<BaseURL serviceLocation="cdn-3">http://content-steering.invalid/cdn3/Eldorado/4sec/avc/</BaseURL>
```

Use this literal placeholder authority. The dash-client delivery proxy replaces
it with the browser-visible scheme, host and port. dash.js intentionally accepts
only the first BaseURL when several relative URLs occur at the same MPD level;
absolute delivered URLs preserve all three native steering choices.

Place ContentSteering at MPD level **after Period**, following the
[MPEG schema element order](https://github.com/MPEGGroup/DASHSchema/blob/6th-Ed/DASH-MPD.xsd):

```xml
<ContentSteering queryBeforeStart="true" defaultServiceLocation="cdn-1">/steering/manifest.json</ContentSteering>
```

Remove the old `cloud` BaseURL and any duplicate ContentSteering element.
SegmentTemplate URLs must resolve relative to these BaseURLs; absolute
representation URLs that bypass the gateways are outside this setup.
Use the same objects and representation layout for all pathways.
The origin and CDN caches keep this packaged MPD unchanged. The dash-client
rewrites only its placeholder authority while delivering the MPD to the browser.
An MPD without ContentSteering can play but will not exercise the CSS.
