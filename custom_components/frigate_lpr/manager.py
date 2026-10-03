"""MQTT and persistence manager."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any, Callable

from aiohttp import ClientError, ClientTimeout
from homeassistant.components import mqtt
from homeassistant.components.image import async_get_image
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import MOTORAPI_URL, SIGNAL_NEW_PLATE, SIGNAL_UPDATE, SNAPSHOT_API_PATH
from .model import LPRRegistry, normalize_plate

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1


class LPRManager:
    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        topic: str,
        camera: str,
        frequent_observations: int,
        frequent_days: int,
        motorapi_enabled: bool = False,
        motorapi_key: str = "",
        snapshots_enabled: bool = False,
        snapshot_entity: str = "",
        speed_enabled: bool = True,
        events_topic: str = "frigate/events",
        speed_unit: str = "kmh",
        speed_limit: float = 50,
        notify_services: tuple[str, ...] = (),
        notify_critical: bool = False,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.topic = topic
        self.camera = camera
        self.frequent_observations = frequent_observations
        self.frequent_days = frequent_days
        self.motorapi_enabled = motorapi_enabled
        self.motorapi_key = motorapi_key
        self.snapshots_enabled = snapshots_enabled
        self.snapshot_entity = snapshot_entity
        self.speed_enabled = speed_enabled
        self.events_topic = events_topic
        self.speed_unit = speed_unit
        self.speed_limit = speed_limit
        self.notify_services = tuple(dict.fromkeys(service for service in notify_services if service))
        self.notify_critical = notify_critical
        self._pending_speeds: dict[str, tuple[float, float | None]] = {}
        self._snapshot_generations: dict[str, int] = {}
        self._snapshot_lock = asyncio.Lock()
        self.snapshot_dir = Path(hass.config.path(".storage", "frigate_lpr_snapshots"))
        self.store = Store(hass, STORAGE_VERSION, f"frigate_lpr.{entry_id}")
        self.registry = LPRRegistry(frequent_observations=frequent_observations, frequent_days=frequent_days)
        self.unsubscribe: Callable[[], None] | None = None
        self.events_unsubscribe: Callable[[], None] | None = None

    async def async_setup(self) -> None:
        stored = await self.store.async_load()
        if stored:
            self.registry = LPRRegistry(
                stored,
                frequent_observations=self.frequent_observations,
                frequent_days=self.frequent_days,
            )
        self.unsubscribe = await mqtt.async_subscribe(self.hass, self.topic, self._message_received, qos=0)
        if self.speed_enabled and self.events_topic:
            self.events_unsubscribe = await mqtt.async_subscribe(
                self.hass, self.events_topic, self._events_message_received, qos=0
            )

    async def async_unload(self) -> None:
        if self.unsubscribe:
            self.unsubscribe()
        if self.events_unsubscribe:
            self.events_unsubscribe()
        await self.store.async_save(self.registry.data)

    @callback
    def _message_received(self, message: mqtt.ReceiveMessage) -> None:
        try:
            payload = json.loads(message.payload)
            if payload.get("type") != "lpr":
                return
            if self.camera and payload.get("camera") != self.camera:
                return
            timestamp = datetime.fromtimestamp(float(payload["timestamp"]), tz=dt_util.UTC)
            timestamp = dt_util.as_local(timestamp)
            plate = payload.get("plate", "")
            normalized_plate = normalize_plate(plate)
            event_id = str(payload.get("id", ""))
            pending_speed = self._pending_speeds.pop(event_id, None)
            is_new_plate = bool(normalized_plate and normalized_plate not in self.registry.plates)
            changed = self.registry.observe(
                plate,
                timestamp,
                event_id,
                camera=str(payload.get("camera", "")),
                score=payload.get("score"),
                frigate_name=payload.get("name"),
                speed_kmh=pending_speed[0] if pending_speed else None,
                velocity_angle=pending_speed[1] if pending_speed else None,
            )
            if not changed:
                return
            record = self.registry.plates.get(normalized_plate, {})
            speeding = bool(pending_speed and pending_speed[0] > self.speed_limit)
            notify_passage = bool(
                self.notify_services
                and (
                    record.get("notify_on_passage")
                    or (record.get("notify_on_speed") and speeding)
                )
            )
            if speeding and record.get("notify_on_speed"):
                observation = next(
                    (
                        item
                        for item in record.get("observations", [])
                        if item.get("event_id") == event_id
                    ),
                    None,
                )
                if observation is not None:
                    observation["speed_notification_sent"] = True
            self.store.async_delay_save(lambda: self.registry.data, 5)
            if is_new_plate:
                async_dispatcher_send(self.hass, f"{SIGNAL_NEW_PLATE}_{self.entry_id}", normalized_plate)
                self.hass.bus.async_fire(
                    "frigate_lpr_new_plate",
                    {
                        "plate": normalized_plate,
                        "camera": payload.get("camera", ""),
                        "timestamp": timestamp.isoformat(),
                    },
                )
                if (
                    self.motorapi_enabled
                    and self.motorapi_key
                    and self.registry.should_lookup_vehicle(normalized_plate)
                ):
                    self.registry.mark_vehicle_lookup(
                        normalized_plate,
                        {
                            "status": "pending",
                            "provider": "motorapi",
                            "attempted_at": dt_util.utcnow().isoformat(),
                        },
                    )
                    self.hass.async_create_task(
                        self._async_lookup_vehicle(normalized_plate),
                        "Frigate LPR vehicle lookup",
                    )
            capture_snapshot = bool(
                self.snapshots_enabled and self.snapshot_entity and normalized_plate
            )
            if capture_snapshot or notify_passage:
                self.hass.async_create_task(
                    self._async_capture_and_notify(
                        normalized_plate,
                        event_id,
                        str(payload.get("camera", "")),
                        timestamp,
                        pending_speed,
                        self._snapshot_generations.get(normalized_plate, 0),
                        capture_snapshot,
                        notify_passage,
                        speeding,
                    ),
                    "Frigate LPR passage snapshot and notification",
                )
            async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            _LOGGER.warning("Ignored invalid Frigate LPR payload", exc_info=True)

    async def _async_notify_passage(
        self,
        plate: str,
        event_id: str,
        timestamp: datetime,
        speed: tuple[float, float | None] | None,
        speeding: bool = False,
    ) -> None:
        """Notify configured Companion App targets for an opted-in vehicle case."""
        record = self.registry.plates.get(plate, {})
        if speed is None:
            observation = next(
                (item for item in record.get("observations", []) if item.get("event_id") == event_id),
                None,
            )
            if observation and observation.get("speed_kmh") is not None:
                speed = (
                    float(observation["speed_kmh"]),
                    observation.get("velocity_angle"),
                )
        vehicle = record.get("vehicle") or {}
        vehicle_name = " ".join(
            str(value) for value in (vehicle.get("make"), vehicle.get("model")) if value
        )
        relation = record.get("name") or vehicle_name
        details = [plate]
        if relation:
            details.append(relation)
        details.append(timestamp.strftime("%H:%M"))
        if speed:
            details.append(f"{speed[0]:.1f} km/t")
        notes = str(record.get("notes") or "").strip()
        message = " · ".join(details)
        if notes:
            message = f"{message}\nBemærkning: {notes}"
        service_data: dict[str, Any] = {
            "title": "Høj hastighed registreret" if speeding else "Køretøj registreret",
            "message": message,
        }
        notification_data: dict[str, Any] = {}
        snapshot = record.get("snapshot") or {}
        if snapshot.get("event_id") == event_id:
            notification_data["image"] = SNAPSHOT_API_PATH.format(plate=plate)
        if self.notify_critical:
            notification_data["push"] = {
                "sound": {
                    "name": "default",
                    "critical": 1,
                    "volume": 1.0,
                }
            }
        if notification_data:
            service_data["data"] = notification_data
        for service in self.notify_services:
            if not self.hass.services.has_service("notify", service):
                _LOGGER.warning("Configured notification service notify.%s is unavailable", service)
                continue
            await self.hass.services.async_call(
                "notify", service, service_data, blocking=False
            )

    async def _async_capture_and_notify(
        self,
        plate: str,
        event_id: str,
        camera: str,
        timestamp: datetime,
        speed: tuple[float, float | None] | None,
        generation: int,
        capture_snapshot: bool,
        notify_passage: bool,
        speeding: bool = False,
    ) -> None:
        """Capture the current passage image before sending its notification."""
        if capture_snapshot:
            await self._async_store_snapshot(plate, event_id, camera, generation)
        if notify_passage:
            await self._async_notify_passage(
                plate, event_id, timestamp, speed, speeding
            )

    @callback
    def _events_message_received(self, message: mqtt.ReceiveMessage) -> None:
        """Receive Frigate tracking updates and attach measured speed by event id."""
        try:
            payload = json.loads(message.payload)
            after = payload.get("after") or {}
            if after.get("label") != "car":
                return
            if self.camera and after.get("camera") != self.camera:
                return
            event_id = str(after.get("id") or "")
            raw_speed = after.get("average_estimated_speed")
            if not event_id or raw_speed is None:
                return
            speed = float(raw_speed)
            if self.speed_unit == "mph":
                speed *= 1.609344
            if speed <= 0:
                return
            angle_value = after.get("velocity_angle")
            angle = float(angle_value) if angle_value is not None else None
            speed = round(speed, 1)
            if self.registry.set_observation_speed(event_id, speed, angle):
                self.store.async_delay_save(lambda: self.registry.data, 5)
                async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")
                self._schedule_speed_notification(event_id, speed, angle)
                return
            if any(event_id in record["event_ids"] for record in self.registry.plates.values()):
                return
            self._pending_speeds[event_id] = (speed, angle)
            # Bound memory if events arrive for vehicles whose plates are never read.
            while len(self._pending_speeds) > 500:
                self._pending_speeds.pop(next(iter(self._pending_speeds)))
        except (ValueError, TypeError, json.JSONDecodeError):
            _LOGGER.warning("Ignored invalid Frigate events payload", exc_info=True)

    def _schedule_speed_notification(
        self, event_id: str, speed: float, angle: float | None
    ) -> None:
        """Send a speed-only alert when speed arrived after the LPR message."""
        if speed <= self.speed_limit or not self.notify_services:
            return
        for plate, record in self.registry.plates.items():
            observation = next(
                (item for item in record["observations"] if item.get("event_id") == event_id),
                None,
            )
            if observation is None:
                continue
            if observation.get("speed_notification_sent"):
                return
            if not record.get("notify_on_speed") or record.get("notify_on_passage"):
                return
            observation["speed_notification_sent"] = True
            self.store.async_delay_save(lambda: self.registry.data, 5)
            self.hass.async_create_task(
                self._async_capture_and_notify(
                    plate,
                    event_id,
                    str(observation.get("camera", "")),
                    datetime.fromisoformat(observation["timestamp"]),
                    (speed, angle),
                    self._snapshot_generations.get(plate, 0),
                    bool(self.snapshots_enabled and self.snapshot_entity),
                    True,
                    True,
                ),
                "Frigate LPR high speed notification",
            )
            return

    async def async_set_metadata(
        self,
        plate: str,
        name: str,
        category: str,
        *,
        notes: str | None = None,
        vehicle: dict[str, Any] | None = None,
        ignored: bool | None = None,
        notify_on_passage: bool | None = None,
        notify_on_speed: bool | None = None,
    ) -> None:
        is_new = normalize_plate(plate) not in self.registry.plates
        key = self.registry.set_metadata(
            plate,
            name,
            category,
            notes=notes,
            vehicle=vehicle,
            ignored=ignored,
            notify_on_passage=notify_on_passage,
            notify_on_speed=notify_on_speed,
        )
        await self.store.async_save(self.registry.data)
        if is_new:
            async_dispatcher_send(self.hass, f"{SIGNAL_NEW_PLATE}_{self.entry_id}", key)
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")

    async def async_update_observation(
        self,
        plate: str,
        event_id: str,
        timestamp: datetime,
        camera: str,
        score: float | None,
        speed_kmh: float | None = None,
    ) -> bool:
        """Update one passage persistently."""
        changed = self.registry.update_observation(
            plate, event_id, timestamp, camera, score, speed_kmh
        )
        if changed:
            await self.store.async_save(self.registry.data)
            async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")
        return changed

    async def async_remove_observation(self, plate: str, event_id: str) -> bool:
        """Remove one passage persistently."""
        changed = self.registry.remove_observation(plate, event_id)
        if changed:
            await self.store.async_save(self.registry.data)
            async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")
        return changed

    async def async_remove_metadata(self, plate: str) -> None:
        self.registry.remove_metadata(plate)
        await self.store.async_save(self.registry.data)
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")

    async def async_lookup_vehicle_manual(self, plate: str) -> None:
        """Explicitly refresh vehicle data for one locally stored case."""
        normalized = normalize_plate(plate)
        if not self.motorapi_enabled or not self.motorapi_key:
            raise ValueError("MotorAPI is not enabled or the API key is missing")
        if normalized not in self.registry.plates:
            raise ValueError("Save the vehicle case before requesting vehicle data")
        result = await self._async_lookup_vehicle(normalized, manual=True)
        if result.get("status") != "success":
            raise ValueError(f"MotorAPI lookup failed: {result.get('status', 'error')}")

    async def _async_lookup_vehicle(self, plate: str, *, manual: bool = False) -> dict[str, Any]:
        """Look up and permanently cache one new, unknown plate."""
        record = self.registry.plates.get(plate, {})
        if not manual and (
            record.get("name")
            or record.get("category") in {"own", "known", "unwanted"}
        ):
            result = {
                "status": "skipped_private",
                "provider": "motorapi",
                "attempted_at": dt_util.utcnow().isoformat(),
            }
            self.registry.mark_vehicle_lookup(plate, result)
            await self.store.async_save(self.registry.data)
            return result

        result: dict[str, Any] = {
            "status": "error",
            "provider": "motorapi",
            "attempted_at": dt_util.utcnow().isoformat(),
        }
        try:
            session = async_get_clientsession(self.hass)
            response = await session.get(
                MOTORAPI_URL.format(plate=plate),
                headers={
                    "Accept": "application/json",
                    "X-AUTH-TOKEN": self.motorapi_key,
                },
                timeout=ClientTimeout(total=15),
            )
            async with response:
                if response.status == 200:
                    payload = await response.json()
                    if isinstance(payload, list):
                        payload = payload[0] if payload else None
                    if isinstance(payload, dict):
                        result = {
                            "status": "success",
                            "provider": "motorapi",
                            "attempted_at": dt_util.utcnow().isoformat(),
                            "trigger": "manual" if manual else "automatic",
                            "vehicle": self._vehicle_data(payload),
                        }
                    else:
                        result["status"] = "not_found"
                elif response.status == 404:
                    result["status"] = "not_found"
                elif response.status in {401, 403}:
                    result["status"] = "authentication_error"
                elif response.status == 429:
                    result["status"] = "quota_exceeded"
                else:
                    result["status"] = "provider_error"
        except (ClientError, TimeoutError, ValueError, TypeError):
            _LOGGER.warning("MotorAPI lookup failed", exc_info=True)

        self.registry.mark_vehicle_lookup(plate, result)
        await self.store.async_save(self.registry.data)
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")
        return result

    async def _async_store_snapshot(
        self, plate: str, event_id: str, camera: str, generation: int
    ) -> None:
        """Copy the current image entity content and retain it on one case."""
        image_bytes: bytes | None = None
        content_type = "image/jpeg"
        for delay in (1, 3, 6):
            try:
                await asyncio.sleep(delay)
                image = await async_get_image(self.hass, self.snapshot_entity)
                if image.content:
                    image_bytes = image.content
                    content_type = image.content_type
                    break
            except (HomeAssistantError, KeyError, TimeoutError):
                continue
        if not image_bytes or len(image_bytes) > 8 * 1024 * 1024:
            _LOGGER.warning("Snapshot image entity was unavailable, empty or oversized")
            return
        try:
            async with self._snapshot_lock:
                if self._snapshot_generations.get(plate, 0) != generation:
                    return
                await self.hass.async_add_executor_job(self._write_snapshot, plate, image_bytes)
                record = self.registry.plates.get(plate)
                if record is None:
                    return
                record["snapshot"] = {
                    "event_id": event_id,
                    "captured_at": dt_util.utcnow().isoformat(),
                    "camera": camera,
                    "source_entity": self.snapshot_entity,
                    "content_type": content_type,
                }
                await self.store.async_save(self.registry.data)
                async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")
        except OSError:
            _LOGGER.warning("Unable to store snapshot from image entity", exc_info=True)

    async def async_remove_snapshot(self, plate: str) -> bool:
        """Remove the retained image without changing the vehicle history."""
        normalized = normalize_plate(plate)
        record = self.registry.plates.get(normalized)
        if record is None:
            return False
        self._snapshot_generations[normalized] = self._snapshot_generations.get(normalized, 0) + 1
        async with self._snapshot_lock:
            await self.hass.async_add_executor_job(self._remove_snapshot_files, normalized)
            record["snapshot"] = None
            await self.store.async_save(self.registry.data)
            async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")
        return True

    def _remove_snapshot_files(self, plate: str) -> None:
        """Remove current and legacy snapshot files outside the event loop."""
        for suffix in (".img", ".jpg"):
            path = self.snapshot_dir / f"{plate}{suffix}"
            if path.is_file():
                path.unlink()

    def _write_snapshot(self, plate: str, image: bytes) -> None:
        """Write a snapshot atomically outside the event loop."""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        target = self.snapshot_dir / f"{normalize_plate(plate)}.img"
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(image)
        temporary.replace(target)

    async def async_snapshot_bytes(self, plate: str) -> bytes | None:
        """Read a locally retained snapshot for the authenticated HTTP view."""
        return await self.hass.async_add_executor_job(self._read_snapshot, plate)

    def _read_snapshot(self, plate: str) -> bytes | None:
        """Read a snapshot outside the event loop."""
        path = self.snapshot_dir / f"{normalize_plate(plate)}.img"
        if not path.is_file():
            path = self.snapshot_dir / f"{normalize_plate(plate)}.jpg"
        if not path.is_file():
            return None
        return path.read_bytes()

    @staticmethod
    def _vehicle_data(payload: dict[str, Any]) -> dict[str, Any]:
        """Keep all master data returned by the MotorAPI vehicle endpoint."""
        return {key: value for key, value in payload.items() if value is not None}
