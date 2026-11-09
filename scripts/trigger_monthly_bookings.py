"""Wake the API and drain bounded monthly batches without logging credentials."""

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main():
    base = os.environ.get("AF_BOOKING_API_URL", "").rstrip("/")
    token = os.environ.get("MONTHLY_BOOKING_TOKEN", "")
    url = urlsplit(base)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path
        or len(token) < 32
    ):
        raise SystemExit("Configure AF_BOOKING_API_URL (HTTPS origin) and MONTHLY_BOOKING_TOKEN.")
    deadline = time.monotonic() + 12 * 60
    for _ in range(30):
        if time.monotonic() >= deadline:
            break
        request = Request(
            base + "/api/v1/internal/bookings/monthly-rollover",
            method="POST",
            headers={"Authorization": "Bearer " + token},
        )
        try:
            with urlopen(request, timeout=150) as response:
                result = json.load(response)
        except HTTPError as error:
            if error.code in {401, 403, 404}:
                raise SystemExit(
                    f"Monthly trigger rejected: HTTP {error.code}. Check deployment and token."
                ) from None
            time.sleep(10)
            continue
        except (URLError, TimeoutError):
            time.sleep(10)
            continue
        if not isinstance(result, dict) or not isinstance(result.get("processed_folders"), int):
            raise SystemExit("Monthly trigger returned an unexpected response.")
        print(f"Period {result.get('period')}: created {result.get('created', 0)} booking(s).")
        if not result.get("enabled") or result["processed_folders"] == 0:
            return
    raise SystemExit("Monthly generation did not finish; rerun to continue from saved progress.")


if __name__ == "__main__":
    main()
