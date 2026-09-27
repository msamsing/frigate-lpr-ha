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
        for record in self.data["plates"].values():
            record.setdefault("vehicle", None)
            record.setdefault("vehicle_lookup", None)
            record.setdefault("vehicle_source", None)
            record.setdefault("notes", "")
        self.frequent_observations = frequent_observations
        self.frequent_days = frequent_days

    @property
    def plates(self) -> dict[str, dict[str, Any]]:
        return self.data["plates"]

    def set_metadata(
        self,
        plate: str,
        name: str,
        category: str,
        *,
        notes: str | None = None,
        vehicle: dict[str, Any] | None = None,
    ) -> str:
        """Add or update user-controlled metadata."""
        key = normalize_plate(plate)
        if not key:
            raise ValueError("Plate cannot be empty")
        record = self.plates.setdefault(key, self._empty_record(key))
        record["name"] = name.strip()
        record["category"] = category
        if notes is not None:
            record["notes"] = notes.strip()
        if vehicle is not None:
            record["vehicle"] = {
                field: value.strip() if isinstance(value, str) else value
                for field, value in vehicle.items()
                if value not in (None, "")
            } or None
            record["vehicle_source"] = "manual" if record["vehicle"] else None
        return key

    def remove_metadata(self, plate: str) -> bool:
        """Clear user metadata without deleting observation history."""
        key = normalize_plate(plate)
        record = self.plates.get(key)
        if not record:
            return False
        record["name"] = ""
        record["category"] = ""
        record["notes"] = ""
        if record.get("vehicle_source") == "manual":
            record["vehicle"] = None
            record["vehicle_source"] = None
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

    def should_lookup_vehicle(self, plate: str) -> bool:
        """Return whether a brand-new unknown plate may be sent to a provider."""
        record = self.plates.get(plate)
        if record is None:
            return False
        return not (
            record.get("name")
            or record.get("category") in {"own", "known"}
            or record.get("vehicle_lookup") is not None
        )

    def mark_vehicle_lookup(self, plate: str, result: dict[str, Any]) -> None:
        """Persist a lookup result so the plate is never looked up automatically again."""
        record = self.plates[plate]
        record["vehicle_lookup"] = result
        if result.get("status") == "success":
            record["vehicle"] = result.get("vehicle")
            record["vehicle_source"] = "motorapi"

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
                {
                    "plate": plate,
                    "count": record["count"],
                    "days": len(record["days"]),
                    "name": record["name"],
                    "vehicle": record.get("vehicle"),
                    "notes": record.get("notes", ""),
                }
                for plate, record in self.plates.items()
            ),
            key=lambda item: (-item["count"], item["plate"]),
        )[:10]
        known = [
            {
                "plate": plate,
                "name": record["name"],
                "category": record["category"],
                "vehicle": record.get("vehicle"),
                "notes": record.get("notes", ""),
            }
            for plate, record in sorted(self.plates.items())
            if record["name"] or record["category"]
        ]
        one_time = [
            {
                "plate": plate,
                "last_seen": record["last_seen"],
                "vehicle": record.get("vehicle"),
                "notes": record.get("notes", ""),
            }
            for plate, record in self.plates.items()
            if record["count"] == 1
        ]
        classified = {name: [] for name in ("Egen", "Kendt lokal", "Hyppig", "Sjælden", "Engangsbesøgende")}
        for plate, record in self.plates.items():
            classification = self.classification(record)
            classified[classification].append(
                {
                    "plate": plate,
                    "name": record["name"] or record["frigate_name"],
                    "count": record["count"],
                    "days": len(record["days"]),
                    "last_seen": record["last_seen"],
                    "classification": classification,
                    "vehicle": record.get("vehicle"),
                    "notes": record.get("notes", ""),
                }
            )
        for items in classified.values():
            items.sort(key=lambda item: (-item["count"], item["plate"]))
        return {
            "unique_today": len(plates_today),
            "observations_today": all_today_count,
            "recent": [
                {**item, "vehicle": self.plates.get(item["plate"], {}).get("vehicle")}
                for item in self.data["recent"][:20]
            ],
            "frequent": frequent,
            "known": known,
            "one_time": sorted(one_time, key=lambda item: item["last_seen"] or "", reverse=True)[:20],
            "own": classified["Egen"],
            "known_local": classified["Kendt lokal"],
            "frequent_class": classified["Hyppig"],
            "rare": classified["Sjælden"],
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
            "vehicle": None,
            "vehicle_lookup": None,
            "vehicle_source": None,
            "notes": "",
        }
