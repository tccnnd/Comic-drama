from __future__ import annotations

import json
import sys
from urllib.error import URLError
from urllib.request import urlopen


URL = "http://127.0.0.1:8000/api/health"


def main() -> int:
    try:
        with urlopen(URL, timeout=2) as response:
            if response.status != 200:
                return 1
            payload = json.loads(response.read().decode("utf-8"))
            return 0 if payload.get("status") == "ok" else 1
    except (OSError, URLError, json.JSONDecodeError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
