from datetime import datetime, timedelta, timezone

import importlib.util
from pathlib import Path
import unittest

MODEL_PATH = Path(__file__).parents[1] / "custom_components" / "frigate_lpr" / "model.py"
SPEC = importlib.util.spec_from_file_location("frigate_lpr_model", MODEL_PATH)
model = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(model)
LPRRegistry = model.LPRRegistry
normalize_plate = model.normalize_plate


class LPRRegistryTests(unittest.TestCase):
    def test_normalize_plate(self):
        self.assertEqual(normalize_plate(" ab 12-345 "), "AB12345")

    def test_observation_stats_and_deduplication(self):
        registry = LPRRegistry()
        first = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
        self.assertTrue(registry.observe("AB12345", first, "event-1", camera="test_camera", score=0.9))
        self.assertFalse(registry.observe("AB12345", first, "event-1", camera="test_camera", score=0.95))
        self.assertTrue(registry.observe("AB12345", first + timedelta(hours=26), "event-2", camera="test_camera"))
        view = registry.plate_view("AB12345")
        self.assertEqual(view["count"], 2)
        self.assertEqual(view["different_days"], 2)
        self.assertEqual(view["intervals_seconds"], [93600])
        self.assertEqual(view["classification"], "Sjælden")

    def test_transparent_classification(self):
        registry = LPRRegistry(frequent_observations=3, frequent_days=2)
        start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        registry.set_metadata("AB12345", "Min bil", "own")
        self.assertEqual(registry.plate_view("AB12345")["classification"], "Egen")
        registry.set_metadata("XX12345", "Nabo", "known")
        self.assertEqual(registry.plate_view("XX12345")["classification"], "Kendt lokal")
        registry.observe("ONE1", start, "1", camera="test_camera")
        self.assertEqual(registry.plate_view("ONE1")["classification"], "Engangsbesøgende")
        for index, hours in enumerate((0, 1, 25)):
            registry.observe("FREQ1", start + timedelta(hours=hours), str(index), camera="test_camera")
        self.assertEqual(registry.plate_view("FREQ1")["classification"], "Hyppig")
        summary = registry.summary("2026-09-02")
        self.assertEqual(summary["own"][0]["plate"], "AB12345")
        self.assertEqual(summary["known_local"][0]["plate"], "XX12345")
        self.assertEqual(summary["frequent_class"][0]["plate"], "FREQ1")
        self.assertEqual(summary["one_time"][0]["plate"], "ONE1")

    def test_roundtrip_persistence_and_daily_summary(self):
        registry = LPRRegistry()
        seen = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
        registry.observe("AA11111", seen, "a", camera="test_camera")
        restored = LPRRegistry(registry.data)
        summary = restored.summary("2026-09-26")
        self.assertEqual(summary["unique_today"], 1)
        self.assertEqual(summary["observations_today"], 1)
        self.assertEqual(summary["one_time"][0]["plate"], "AA11111")

    def test_vehicle_lookup_privacy_and_cache(self):
        registry = LPRRegistry()
        seen = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)

        registry.set_metadata("OWN123", "Egen bil", "own")
        registry.observe("OWN123", seen, "own", camera="test_camera")
        self.assertFalse(registry.should_lookup_vehicle("OWN123"))

        registry.set_metadata("KNOWN1", "Kendt bil", "known")
        registry.observe("KNOWN1", seen, "known", camera="test_camera")
        self.assertFalse(registry.should_lookup_vehicle("KNOWN1"))

        registry.observe("NEW123", seen, "new", camera="test_camera")
        self.assertTrue(registry.should_lookup_vehicle("NEW123"))
        registry.mark_vehicle_lookup(
            "NEW123",
            {
                "status": "success",
                "provider": "motorapi",
                "vehicle": {"make": "VOLVO", "model": "XC40"},
            },
        )
        self.assertFalse(registry.should_lookup_vehicle("NEW123"))
        restored = LPRRegistry(registry.data)
        self.assertFalse(restored.should_lookup_vehicle("NEW123"))
        recent = restored.summary("2026-09-27")["recent"]
        new_vehicle = next(item for item in recent if item["plate"] == "NEW123")["vehicle"]
        self.assertEqual(new_vehicle["model"], "XC40")

    def test_manual_vehicle_case_roundtrip(self):
        registry = LPRRegistry()
        registry.set_metadata(
            "CASE123",
            "Gæstebil",
            "known",
            notes="Må parkere ved bygning A.",
            vehicle={
                "make": "Skoda",
                "model": "Enyaq",
                "model_year": 2024,
                "color": "Blå",
            },
        )
        restored = LPRRegistry(registry.data)
        case = restored.plate_view("CASE123")
        self.assertEqual(case["classification"], "Kendt lokal")
        self.assertEqual(case["notes"], "Må parkere ved bygning A.")
        self.assertEqual(case["vehicle"]["model"], "Enyaq")
        self.assertEqual(case["vehicle_source"], "manual")
        self.assertFalse(restored.should_lookup_vehicle("CASE123"))


if __name__ == "__main__":
    unittest.main()
