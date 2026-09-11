from urllib.parse import urlencode


class DashParser:
    def build(self, priority, parameters=None, ttl=5, path="/manifest.json"):
        # Origin-relative URI also works when the MPD's CSS URL is relative.
        reload_uri = path
        if parameters:
            reload_uri += "?" + urlencode(parameters)
        return {
            "VERSION": 1,
            "TTL": ttl,
            "RELOAD-URI": reload_uri,
            "PATHWAY-PRIORITY": list(priority),
        }
