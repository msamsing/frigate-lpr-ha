"""Data model independent from Home Assistant for easy testing."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import math
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
            merged_vehicle = dict(record.get("vehicle") or {})
            for field, value in vehicle.items():
                if value in (None, ""):
                    merged_vehicle.pop(field, None)
                else:
                    merged_vehicle[field] = value.strip() if isinstance(value, str) else value
            record["vehicle"] = merged_vehicle or None
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
        if record.get("category") == "known":
            return "Kendt lokal"
        if record.get("category") == "unwanted":
            return "Uønsket"
        if record.get("category") == "unknown":
            return "Ukendt"
        if record.get("name"):
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
            "time_stats": self._time_stats(record["observations"]),
        }

    @staticmethod
    def _time_stats(observations: list[dict[str, Any]]) -> dict[str, Any]:
        """Return compact aggregates used by the dashboard charts."""
        if not observations:
            return {
                "last_7_days": 0,
                "last_30_days": 0,
                "typical_minute": None,
                "spread_minutes": None,
                "earliest_minute": None,
                "latest_minute": None,
                "hour_counts": [0] * 24,
                "daily_counts": [],
            }
        timestamps = [datetime.fromisoformat(item["timestamp"]) for item in observations]
        now = datetime.now(timestamps[-1].tzinfo or timezone.utc)
        aware = [stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc) for stamp in timestamps]
        minutes = [stamp.hour * 60 + stamp.minute for stamp in timestamps]
        angles = [minute / 1440 * 2 * math.pi for minute in minutes]
        mean_angle = math.atan2(
            sum(math.sin(angle) for angle in angles),
            sum(math.cos(angle) for angle in angles),
        )
        typical = round((mean_angle % (2 * math.pi)) / (2 * math.pi) * 1440) % 1440
        circular_distances = [min(abs(minute - typical), 1440 - abs(minute - typical)) for minute in minutes]
        hour_counts = [0] * 24
        for minute in minutes:
            hour_counts[minute // 60] += 1
        daily = Counter(stamp.date().isoformat() for stamp in timestamps)
        return {
            "last_7_days": sum(stamp >= now - timedelta(days=7) for stamp in aware),
            "last_30_days": sum(stamp >= now - timedelta(days=30) for stamp in aware),
            "typical_minute": typical,
            "spread_minutes": round(sum(circular_distances) / len(circular_distances)),
            "earliest_minute": min(minutes),
            "latest_minute": max(minutes),
            "hour_counts": hour_counts,
            "daily_counts": [
                {"date": (now.date() - timedelta(days=offset)).isoformat(), "count": daily.get((now.date() - timedelta(days=offset)).isoformat(), 0)}
                for offset in range(6, -1, -1)
            ],
        }

    def should_lookup_vehicle(self, plate: str) -> bool:
        """Return whether a brand-new unknown plate may be sent to a provider."""
        record = self.plates.get(plate)
        if record is None:
            return False
        return not (
            record.get("name")
            or record.get("category") in {"own", "known", "unwanted"}
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
        classified = {
            name: []
            for name in (
                "Egen",
                "Kendt lokal",
                "Uønsket",
                "Ukendt",
                "Hyppig",
                "Sjælden",
                "Engangsbesøgende",
            )
        }
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
                {
                    **item,
                    "vehicle": self.plates.get(item["plate"], {}).get("vehicle"),
                    "name": self.plates.get(item["plate"], {}).get("name", ""),
                    "category": self.plates.get(item["plate"], {}).get("category", ""),
                    "classification": self.classification(self.plates[item["plate"]]),
                }
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
