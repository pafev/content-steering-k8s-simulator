import json


def parse_access_log_datagram(raw: bytes) -> dict:
    """Extract the JSON payload from an Nginx syslog UDP datagram."""
    message = raw.decode("utf-8").strip()
    json_start = message.find("{")
    if json_start < 0:
        raise json.JSONDecodeError("missing JSON object", message, 0)
    return json.loads(message[json_start:])
