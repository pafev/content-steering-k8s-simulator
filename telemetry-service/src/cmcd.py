import json
from urllib.parse import parse_qs, urlsplit


CMCD_HEADERS = (
    "cmcd",
    "cmcd-request",
    "cmcd-object",
    "cmcd-status",
    "cmcd-session",
)


def _split_pairs(value: str) -> list[str]:
    pairs, current = [], []
    quoted = False
    escaped = False
    parentheses = 0
    for char in value:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\" and quoted:
            current.append(char)
            escaped = True
        elif char == '"':
            current.append(char)
            quoted = not quoted
        elif char == "(" and not quoted:
            parentheses += 1
            current.append(char)
        elif char == ")" and not quoted:
            parentheses = max(0, parentheses - 1)
            current.append(char)
        elif char == "," and not quoted and parentheses == 0:
            pairs.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        pairs.append("".join(current).strip())
    return [pair for pair in pairs if pair]


def _parse_scalar(raw_value: str):
    if raw_value.startswith('"') and raw_value.endswith('"'):
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            return raw_value
    if raw_value == "?1":
        return True
    if raw_value == "?0":
        return False
    try:
        return float(raw_value) if "." in raw_value else int(raw_value)
    except ValueError:
        return raw_value


def _parse_inner_list(raw_value: str) -> list[dict]:
    members, current, quoted, escaped = [], [], False, False
    for char in raw_value[1:-1].strip():
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\" and quoted:
            current.append(char)
            escaped = True
        elif char == '"':
            current.append(char)
            quoted = not quoted
        elif char == " " and not quoted:
            if current:
                members.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        members.append("".join(current))

    result = []
    for member in members:
        value, *parameters = member.split(";")
        result.append(
            {
                "value": _parse_scalar(value),
                "parameters": [parameter for parameter in parameters if parameter],
            }
        )
    return result


def parse_cmcd(value: str | None) -> dict:
    if not value:
        return {}
    parsed = {}
    for pair in _split_pairs(value):
        if "=" not in pair:
            parsed[pair] = True
            continue
        key, raw_value = pair.split("=", 1)
        key, raw_value = key.strip(), raw_value.strip()
        if not key:
            continue
        if raw_value.startswith("(") and raw_value.endswith(")"):
            parsed[key] = _parse_inner_list(raw_value)
        else:
            parsed[key] = _parse_scalar(raw_value)
    return parsed


def cmcd_value(data: dict, key: str, object_type: str | None = None):
    """Return a scalar, selecting an object-type value from CMCD v2 lists."""
    value = data.get(key)
    if not isinstance(value, list):
        return value
    if object_type:
        for item in value:
            if object_type in item.get("parameters", []):
                return item.get("value")
    return value[0].get("value") if value else None


def _header_value(headers: dict, expected_name: str) -> str | None:
    for name, value in (headers or {}).items():
        if name.lower() != expected_name:
            continue
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        return str(value)
    return None


def extract_cmcd(access_log: dict) -> dict:
    request_data = access_log.get("request") or {}
    headers = request_data.get("headers") or {}
    result = {}
    has_headers = False
    for header_name in CMCD_HEADERS:
        value = _header_value(headers, header_name)
        if value:
            has_headers = True
            result.update(parse_cmcd(value))
    if has_headers:
        return result

    uri = request_data.get("uri") or ""
    raw_query_value = parse_qs(urlsplit(uri).query).get("CMCD", [None])[0]
    return parse_cmcd(raw_query_value)
