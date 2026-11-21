"""Replay synthetic Role D connected-vehicle readings against the local demo."""

import argparse
from http.cookiejar import CookieJar
import json
import math
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, HTTPCookieProcessor, Request
from uuid import uuid4


SAMPLES = Path(__file__).with_name("samples") / "connected_vehicles_dataset.json"


def run(port, interval, count, anomaly):
    origin = f"http://127.0.0.1:{port}"
    client = build_opener(HTTPCookieProcessor(CookieJar()))

    def api(path, body=None):
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        req = Request(origin + path, data=encoded, headers={
            "Content-Type": "application/json", "Origin": origin})
        with client.open(req, timeout=10) as response:
            return json.load(response)

    if not api("/api/health")["simulator"]:
        raise ValueError("Start the local server with --simulator to replay synthetic readings.")
    api("/api/login", {"username": "operator",
                       "password": os.getenv("EMOBILITY_OPERATOR_PASSWORD", "operator-demo")})
    vehicles = {row["id"] for row in api("/api/state")["vehicles"] if row["kind"] == "shared"}
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    # The supplied dataset pads numeric identifiers (V01, H01). Match only
    # shared vehicles that already exist in this installation.
    fleet = [(f"V{int(row['resourceId'][1:])}", row) for row in samples]
    fleet = [(vid, row) for vid, row in fleet if vid in vehicles]
    if not fleet:
        raise ValueError("No matching shared vehicles for the sample dataset.")

    step = 0
    while count is None or step < count:
        for vid, sample in fleet:
            event = uuid4().hex
            payload = dict(resourceId=vid, event_id=event, observed_at=time.time(),
                           batterySoc=sample["batterySoc"], speed=sample["speed"],
                           temperatureC=sample["batteryTempC"],
                           destinationHubId=f"H{int(sample['destinationHubId'][1:])}")
            if vid == fleet[0][0]:
                if anomaly == "LOW_BATTERY":
                    payload["batterySoc"] = 12.5
                elif anomaly == "OVERSPEED":
                    payload["speed"] = 115.0
                elif anomaly == "RAPID_DRAIN":
                    payload["batterySoc"] = max(0, payload["batterySoc"] - step * 6.0)
                elif anomaly == "INVALID_ID":
                    payload["resourceId"] = "VEH-9999"
            result = api("/api/commands", {"action": "d_telemetry", "intent_id": event,
                                           "payload": payload})
            alerts = ", ".join(result["record"]["alerts"]) or "none"
            print(f"{vid}  SoC {payload['batterySoc']}%  {payload['speed']} km/h  alerts: {alerts}",
                  flush=True)
        step += 1
        if count is None or step < count:
            time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between batches")
    parser.add_argument("--count", type=int, help="Number of batches (default: until interrupted)")
    parser.add_argument("--anomaly", choices=["LOW_BATTERY", "OVERSPEED", "RAPID_DRAIN", "INVALID_ID"])
    args = parser.parse_args()
    if not math.isfinite(args.interval) or args.interval <= 0 or (args.count is not None and args.count < 1):
        parser.error("--interval and --count must be positive")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        run(args.port, args.interval, args.count, args.anomaly)
    except KeyboardInterrupt:
        return
    except HTTPError as exc:
        parser.exit(1, f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}\n")
    except (URLError, OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
