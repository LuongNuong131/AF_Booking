"""Real HTTP load; private per-session tokens come from a temporary 0600 file."""

import itertools
import json
import math
import os
import random
import re
import time
from pathlib import Path
from uuid import uuid4

from locust import HttpUser, between, events, task

PRIVATE = json.loads(Path(os.environ["LOAD_TOKEN_FILE"]).read_text())
SLOTS = itertools.count()
SAMPLES = []
START = time.monotonic()
MODE = os.environ.get("LOAD_MODE", "mixed")


@events.request.add_listener
def observe(
    request_type, name, response_time, response_length, response=None, exception=None, **kwargs
):
    if time.monotonic() - START < float(os.environ.get("LOAD_WARMUP_SECONDS", "10")):
        return
    timing = (
        re.search(r"(?:^|,\s*)total;dur=([0-9.]+)", response.headers.get("Server-Timing", ""))
        if response is not None
        else None
    )
    SAMPLES.append(
        {
            "name": name,
            "client_ms": response_time,
            "server_ms": float(timing[1]) if timing else None,
            "status": response.status_code if response is not None else 0,
            "failed": exception is not None or response is None or response.status_code >= 400,
        }
    )


def summary(rows, field):
    values = sorted(r[field] for r in rows if r[field] is not None)
    return {
        "count": len(values),
        **{
            f"p{int(q * 100)}_ms": round(values[max(0, math.ceil(len(values) * q) - 1)], 3)
            if values
            else None
            for q in [0.5, 0.95, 0.99]
        },
    }


@events.quitting.add_listener
def finish(environment, **kwargs):
    groups = sorted({r["name"] for r in SAMPLES})
    output = {
        "mode": MODE,
        "warmup_seconds": float(os.environ.get("LOAD_WARMUP_SECONDS", "10")),
        "rest": summary(SAMPLES, "client_ms"),
        "errors": sum(r["failed"] for r in SAMPLES),
        "groups": {
            name: {
                "client": summary([r for r in SAMPLES if r["name"] == name], "client_ms"),
                "server": summary([r for r in SAMPLES if r["name"] == name], "server_ms"),
            }
            for name in groups
        },
    }
    Path(os.environ["LOAD_RESULT_FILE"]).write_text(json.dumps(output, indent=2) + "\n")
    if output["errors"] or not output["rest"]["count"]:
        environment.process_exit_code = 1


class BookingUser(HttpUser):
    wait_time = between(0.4, 0.8)

    def on_start(self):
        self.slot = next(SLOTS)
        self.client.headers["Authorization"] = "Bearer " + PRIVATE["tokens"][self.slot]
        self.version = PRIVATE["initial_version"]
        self.key = PRIVATE["keys"][self.slot]
        self.rng = random.Random(1000 + self.slot)
        self.number = 0
        self.pending = None

    def lookup(self):
        key = self.rng.choice(PRIVATE["keys"])
        case = self.number % 4
        self.number += 1
        if case == 1:
            key = "CW9999999-RDU-2611"
        elif case == 2:
            parts = key.split("-")
            key = parts[0] + "-" + parts[2]
        elif case == 3:
            key = key.replace("CW", "cw ").replace("-", " - ").lower()
        self.client.get(
            "/api/v1/bookings/lookup",
            params={"key": key},
            name=["lookup/full", "lookup/missing", "lookup/partial", "lookup/formatted"][case],
        )

    @task
    def work(self):
        choice = self.rng.random()
        if MODE == "keys" or choice < 0.65:
            self.lookup()
        elif choice < 0.8:
            if self.pending is None:
                self.pending = {
                    "status_code": "BUNDLE",
                    "note": f"Load operation {self.slot}-{uuid4()}",
                    "expected_version": self.version,
                    "client_request_id": str(uuid4()),
                }
            with self.client.post(
                "/api/v1/bookings/" + self.key + "/notes",
                json=self.pending,
                name="notes/save",
                catch_response=True,
            ) as response:
                if response.status_code == 200:
                    self.version = response.json()["snapshot"]["version"]
                    self.pending = None
                elif response.status_code == 409:
                    response.failure("VERSION_CONFLICT")
                    self.version = response.json().get("details", {}).get("version", self.version)
                    self.pending = None
        elif choice < 0.95:
            self.client.get(
                "/api/v1/bookings/mine", params={"page": 1, "size": 10}, name="list/mine"
            )
        elif self.slot in [0, 1]:
            self.client.get(
                "/api/v1/reports/daily", params={"date": PRIVATE["today"]}, name="reports/daily"
            )
        else:
            self.client.get(
                "/api/v1/search/notes",
                params={
                    "q": "supplier",
                    "date_from": PRIVATE["today"],
                    "date_to": PRIVATE["today"],
                },
                name="search/notes",
            )
