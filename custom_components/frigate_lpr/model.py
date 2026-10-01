"""Data model independent from Home Assistant for easy testing."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import math
from statistics import median
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
            record.setdefault("snapshot", None)
            record.setdefault("ignored", False)
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
        ignored: bool | None = None,
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
        if ignored is not None:
            record["ignored"] = ignored
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
        self._recalculate_record(record)
        if frigate_name and not record["name"]:
            record["frigate_name"] = frigate_name

        self.data["recent"].append({"plate": key, **observation})
        self.data["recent"] = sorted(self.data["recent"], key=lambda item: item["timestamp"], reverse=True)[:100]
        return True

    def update_observation(
        self,
        plate: str,
        event_id: str,
        timestamp: datetime,
        camera: str,
        score: float | None,
    ) -> bool:
        """Update one stored passage and all derived values."""
        key = normalize_plate(plate)
        record = self.plates.get(key)
        if record is None:
            return False
        observation = next(
            (item for item in record["observations"] if item.get("event_id") == event_id),
            None,
        )
        if observation is None:
            return False
        observation.update(
            timestamp=timestamp.isoformat(),
            camera=camera,
            score=score,
        )
        self._recalculate_record(record)
        for recent in self.data["recent"]:
            if recent["plate"] == key and recent.get("event_id") == event_id:
                recent.update(observation)
        self.data["recent"].sort(key=lambda item: item["timestamp"], reverse=True)
        return True

    def remove_observation(self, plate: str, event_id: str) -> bool:
        """Delete one stored passage and all derived values."""
        key = normalize_plate(plate)
        record = self.plates.get(key)
        if record is None:
            return False
        before = len(record["observations"])
        record["observations"] = [
            item for item in record["observations"] if item.get("event_id") != event_id
        ]
        if len(record["observations"]) == before:
            return False
        self.data["recent"] = [
            item
            for item in self.data["recent"]
            if not (item["plate"] == key and item.get("event_id") == event_id)
        ]
        self._recalculate_record(record)
        return True

    @staticmethod
    def _recalculate_record(record: dict[str, Any]) -> None:
        """Rebuild counters after an observation is added, edited or removed."""
        record["observations"].sort(key=lambda item: item["timestamp"])
        timestamps = [datetime.fromisoformat(item["timestamp"]) for item in record["observations"]]
        record["event_ids"] = [
            item["event_id"] for item in record["observations"] if item.get("event_id")
        ]
        record["intervals_seconds"] = [
            max(0, int((current - previous).total_seconds()))
            for previous, current in zip(timestamps, timestamps[1:])
        ]
        record["count"] = len(record["observations"])
        record["first_seen"] = record["observations"][0]["timestamp"] if record["observations"] else None
        record["last_seen"] = record["observations"][-1]["timestamp"] if record["observations"] else None
        record["days"] = sorted({item["timestamp"][:10] for item in record["observations"]})

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
            "pattern": self._pattern_analysis(record["observations"]),
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

    @staticmethod
    def _pattern_analysis(observations: list[dict[str, Any]]) -> dict[str, Any]:
        """Describe recurring behavior using explicit, inspectable rules."""
        count = len(observations)
        if not count:
            return {"primary": "Ingen observationer", "secondary": [], "confidence": "Ingen", "evidence": []}
        timestamps = sorted(datetime.fromisoformat(item["timestamp"]) for item in observations)
        active_dates = sorted({stamp.date() for stamp in timestamps})
        days = len(active_dates)
        confidence = "Høj" if count >= 25 and days >= 10 else "Middel" if count >= 10 and days >= 5 else "Lav"
        if count == 1:
            return {
                "primary": "Kun observeret én gang",
                "secondary": [],
                "confidence": "Lav",
                "evidence": ["1 observation på 1 dag"],
            }
        if count < 5 or days < 2:
            return {
                "primary": "For lidt data til et sikkert mønster",
                "secondary": [],
                "confidence": "Lav",
                "evidence": [f"{count} observationer på {days} dag{'e' if days != 1 else ''}"],
            }

        minutes = [stamp.hour * 60 + stamp.minute for stamp in timestamps]
        periods = (
            ("om natten", 0, 300),
            ("om morgenen", 300, 540),
            ("om formiddagen", 540, 720),
            ("om eftermiddagen", 720, 1020),
            ("om aftenen", 1020, 1320),
            ("sent om aftenen", 1320, 1440),
        )
        period_counts = [(label, sum(start <= minute < end for minute in minutes)) for label, start, end in periods]
        dominant_label, dominant_count = max(period_counts, key=lambda item: item[1])
        dominant_share = dominant_count / count

        two_hour_bins = [0] * 12
        for minute in minutes:
            two_hour_bins[minute // 120] += 1
        peaks = sorted(range(12), key=lambda index: two_hour_bins[index], reverse=True)[:2]
        separated = min(abs(peaks[0] - peaks[1]), 12 - abs(peaks[0] - peaks[1])) >= 2
        bimodal = count >= 10 and separated and all(two_hour_bins[index] / count >= 0.2 for index in peaks)

        weekday = sum(stamp.weekday() < 5 for stamp in timestamps)
        weekend = count - weekday
        weekday_density = weekday / 5
        weekend_density = weekend / 2
        weekday_text = None
        if weekday_density >= weekend_density * 1.5 and weekday / count >= 0.65:
            weekday_text = "Ses typisk på hverdage"
        elif weekend_density >= weekday_density * 1.5 and weekend / count >= 0.45:
            weekday_text = "Ses primært i weekender"

        date_counts = Counter(stamp.date() for stamp in timestamps)
        per_active_day = median(date_counts.values())
        intervals = [(current - previous).days for previous, current in zip(active_dates, active_dates[1:])]
        median_interval = median(intervals) if intervals else None
        interval_spread = median([abs(value - median_interval) for value in intervals]) if intervals else None

        latest = timestamps[-1]
        zone = latest.tzinfo or timezone.utc
        now = datetime.now(zone)
        recent_30 = sum(stamp >= now - timedelta(days=30) for stamp in timestamps)
        previous_30 = sum(now - timedelta(days=60) <= stamp < now - timedelta(days=30) for stamp in timestamps)

        stats = LPRRegistry._time_stats(observations)
        evidence = [f"{count} observationer på {days} forskellige dage"]
        secondary: list[str] = []
        if bimodal:
            peak_times = sorted((index * 120 + 60 for index in peaks))
            primary = f"To tydelige tidspunkter omkring {peak_times[0] // 60:02d}:00 og {peak_times[1] // 60:02d}:00"
            evidence.append(f"{sum(two_hour_bins[index] for index in peaks) / count:.0%} ligger i de to største tidsklynger")
        elif dominant_share >= 0.7 and (stats["spread_minutes"] or 0) <= 90:
            primary = f"Regelmæssigt mønster {dominant_label}"
            evidence.append(f"{dominant_share:.0%} af observationerne er {dominant_label}")
        elif median_interval is not None and 5 <= median_interval <= 9 and (interval_spread or 0) <= 2:
            primary = "Omtrent ugentlig rytme"
            evidence.append(f"Typisk {median_interval:g} dage mellem aktive dage")
        elif count >= 8 and days >= 4:
            primary = "Hyppigt, men uden et fast tidspunkt"
        else:
            primary = "Uregelmæssige observationer"

        if weekday_text:
            secondary.append(weekday_text)
            evidence.append(f"{weekday / count:.0%} af observationerne er på hverdage")
        if per_active_day >= 2:
            secondary.append(f"Typisk {per_active_day:g} passager på aktive dage")
        if previous_30 >= 3 and recent_30 >= previous_30 * 1.5:
            secondary.append("Observeres oftere end i den foregående 30-dages periode")
            evidence.append(f"{recent_30} mod {previous_30} passager i de to seneste 30-dages perioder")
        elif recent_30 >= 3 and previous_30 >= recent_30 * 1.5:
            secondary.append("Observeres sjældnere end i den foregående 30-dages periode")
            evidence.append(f"{recent_30} mod {previous_30} passager i de to seneste 30-dages perioder")

        return {
            "primary": primary,
            "secondary": secondary[:2],
            "confidence": confidence,
            "evidence": evidence[:4],
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
        visible_plates = {
            plate: record for plate, record in self.plates.items() if not record.get("ignored")
        }
        plates_today = {
            plate
            for plate, record in visible_plates.items()
            for item in record["observations"]
            if item["timestamp"][:10] == today
        }
        all_today_count = sum(
            1
            for record in visible_plates.values()
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
                for plate, record in visible_plates.items()
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
            for plate, record in visible_plates.items()
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
        for plate, record in visible_plates.items():
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
                for item in self.data["recent"]
                if not self.plates.get(item["plate"], {}).get("ignored")
            ][:20],
            "frequent": frequent,
            "known": known,
            "one_time": sorted(one_time, key=lambda item: item["last_seen"] or "", reverse=True)[:20],
            "own": classified["Egen"],
            "known_local": classified["Kendt lokal"],
            "frequent_class": classified["Hyppig"],
            "rare": classified["Sjælden"],
            "total_unique": len(self.plates),
            "classifications": dict(Counter(self.classification(record) for record in self.plates.values())),
            "traffic_stats": self._traffic_stats(visible_plates),
        }

    def _traffic_stats(self, records: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Aggregate road traffic from all non-ignored passages."""
        observations = [
            (plate, record, item)
            for plate, record in records.items()
            for item in record["observations"]
        ]
        hour_counts = [0] * 24
        weekday_counts = [0] * 7
        categories = {"known": 0, "unknown": 0, "unwanted": 0}
        timestamps: list[datetime] = []
        for _plate, record, item in observations:
            stamp = datetime.fromisoformat(item["timestamp"])
            timestamps.append(stamp)
            hour_counts[stamp.hour] += 1
            weekday_counts[stamp.weekday()] += 1
            classification = self.classification(record)
            if classification in {"Egen", "Kendt lokal"}:
                categories["known"] += 1
            elif classification == "Uønsket":
                categories["unwanted"] += 1
            else:
                categories["unknown"] += 1
        now = datetime.now((timestamps[-1].tzinfo if timestamps else None) or timezone.utc)
        recent_7 = sum(stamp >= now - timedelta(days=7) for stamp in timestamps)
        recent_30 = sum(stamp >= now - timedelta(days=30) for stamp in timestamps)
        today = sum(stamp.date() == now.date() for stamp in timestamps)
        total = len(observations)
        busiest_hour = max(range(24), key=lambda hour: hour_counts[hour]) if total else None
        busiest_weekday = max(range(7), key=lambda day: weekday_counts[day]) if total else None
        return {
            "total_passages": total,
            "unique_vehicles": len(records),
            "today": today,
            "last_7_days": recent_7,
            "last_30_days": recent_30,
            "daily_average_30": round(recent_30 / 30, 1),
            "hour_counts": hour_counts,
            "weekday_counts": weekday_counts,
            "categories": categories,
            "busiest_hour": busiest_hour,
            "busiest_weekday": busiest_weekday,
            "ignored_vehicles": sum(record.get("ignored", False) for record in self.plates.values()),
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
            "snapshot": None,
            "ignored": False,
        }
