"""Data model independent from Home Assistant for easy testing."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import re
from typing import Any

PLATE_RE = re.compile(r"[^A-Z0-9]")


def normalize_plate(value: str) -> str:
    """Normalize a plate for stable identity."""
    return PLATE_RE.sub("", value.upper().strip())


class LPRRegistry:
    """Persistent registry and transparent classification logic."""

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        *,
        frequent_observations: int = 10,
        frequent_days: int = 4,
    ) -> None:
        self.data = data or {"version": 1, "plates": {}, "recent": []}
        self.data.setdefault("plates", {})
        self.data.setdefault("recent", [])
        self.frequent_observations = frequent_observations
        self.frequent_days = frequent_days

    @property
    def plates(self) -> dict[str, dict[str, Any]]:
        return self.data["plates"]

    def set_metadata(self, plate: str, name: str, category: str) -> str:
        """Add or update user-controlled metadata."""
        key = normalize_plate(plate)
        if not key:
            raise ValueError("Plate cannot be empty")
        record = self.plates.setdefault(key, self._empty_record(key))
        record["name"] = name.strip()
        record["category"] = category
        return key

    def remove_metadata(self, plate: str) -> bool:
        """Clear user metadata without deleting observation history."""
        key = normalize_plate(plate)
        record = self.plates.get(key)
        if not record:
            return False
        record["name"] = ""
        record["category"] = ""
        if record["count"] == 0:
            del self.plates[key]
        return True

    def observe(
        self,
        plate: str,
        timestamp: datetime,
        event_id: str,
        *,
        camera: str,
        score: float | None = None,
        frigate_name: str | None = None,
    ) -> bool:
        """Record one distinct Frigate vehicle event; return whether it was new."""
        key = normalize_plate(plate)
        if not key:
            return False
        record = self.plates.setdefault(key, self._empty_record(key))
        if event_id and event_id in record["event_ids"]:
            return False

        iso = timestamp.isoformat()
        observation = {
            "timestamp": iso,
            "event_id": event_id,
            "camera": camera,
            "score": score,
        }
        record["observations"].append(observation)
        if event_id:
            record["event_ids"].append(event_id)
        record["observations"].sort(key=lambda item: item["timestamp"])
        timestamps = [datetime.fromisoformat(item["timestamp"]) for item in record["observations"]]
        record["intervals_seconds"] = [
            max(0, int((current - previous).total_seconds()))
            for previous, current in zip(timestamps, timestamps[1:])
        ]
        record["first_seen"] = record["observations"][0]["timestamp"]
        record["last_seen"] = record["observations"][-1]["timestamp"]
        record["count"] += 1
        record["days"] = sorted({item["timestamp"][:10] for item in record["observations"]})
        if frigate_name and not record["name"]:
            record["frigate_name"] = frigate_name

        self.data["recent"].append({"plate": key, **observation})
        self.data["recent"] = sorted(self.data["recent"], key=lambda item: item["timestamp"], reverse=True)[:100]
        return True

    def classification(self, record: dict[str, Any]) -> str:
        """Classify solely from explicit metadata and observable frequency."""
        if record.get("category") == "own":
            return "Egen"
        if record.get("category") == "known" or record.get("name"):
            return "Kendt lokal"
        if (
            record["count"] >= self.frequent_observations
            and len(record["days"]) >= self.frequent_days
        ):
            return "Hyppig"
        if record["count"] == 1:
            return "Engangsbesøgende"
        return "Sjælden"

    def plate_view(self, plate: str) -> dict[str, Any]:
        record = self.plates[plate]
        intervals = record["intervals_seconds"]
        return {
            **record,
            "classification": self.classification(record),
            "different_days": len(record["days"]),
            "average_interval_hours": round(sum(intervals) / len(intervals) / 3600, 1) if intervals else None,
        }

    def summary(self, today: str) -> dict[str, Any]:
        plates_today = {
            plate
            for plate, record in self.plates.items()
            for item in record["observations"]
            if item["timestamp"][:10] == today
        }
        all_today_count = sum(
            1
            for record in self.plates.values()
            for item in record["observations"]
            if item["timestamp"][:10] == today
        )
        frequent = sorted(
            (
                {"plate": plate, "count": record["count"], "days": len(record["days"]), "name": record["name"]}
                for plate, record in self.plates.items()
            ),
            key=lambda item: (-item["count"], item["plate"]),
        )[:10]
        known = [
            {"plate": plate, "name": record["name"], "category": record["category"]}
            for plate, record in sorted(self.plates.items())
            if record["name"] or record["category"]
        ]
        one_time = [
            {"plate": plate, "last_seen": record["last_seen"]}
            for plate, record in self.plates.items()
            if record["count"] == 1
        ]
        return {
            "unique_today": len(plates_today),
            "observations_today": all_today_count,
            "recent": self.data["recent"][:20],
            "frequent": frequent,
            "known": known,
            "one_time": sorted(one_time, key=lambda item: item["last_seen"] or "", reverse=True)[:20],
            "total_unique": len(self.plates),
            "classifications": dict(Counter(self.classification(record) for record in self.plates.values())),
        }

    @staticmethod
    def _empty_record(plate: str) -> dict[str, Any]:
        return {
            "plate": plate,
            "name": "",
            "category": "",
            "frigate_name": "",
            "first_seen": None,
            "last_seen": None,
            "count": 0,
            "days": [],
            "intervals_seconds": [],
            "observations": [],
            "event_ids": [],
        }
