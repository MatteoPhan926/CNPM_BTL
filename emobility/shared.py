"""Shared policy and validation primitives for the four mobility modules."""
import hashlib
import json
import math

POLICY = dict(freshness=90, hold_seconds=600, no_show=600, parking_buffer=900,
              max_advance=86400, min_parking=900, max_parking=43200,
              rental_soc=20, ordinary_capacity=.90, warning=.80, high=.95,
              ack_timeout=60, unplug_reminder=900, efficiency=.90)
LIVE_RIGHT = {'CONFIRMED', 'HANDOVER_PENDING', 'OFFERED'}
LIVE_SESSION = {'BOOKED', 'START_PENDING', 'CHARGING', 'STOP_PENDING'}


class DomainError(Exception):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def require(ok, code, message, status=409):
    if not ok:
        raise DomainError(code, message, status)


def number(value, name, low=0, high=10**12):
    require(type(value) in (int, float) and low <= value <= high and math.isfinite(value),
            'INVALID_INPUT', f'{name} must be a finite number from {low} to {high}.', 400)
    return float(value)


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def overlap(a, b, c, d):
    return a < d and c < b
