"""MQTT and persistence manager."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from aiohttp import ClientError, ClientTimeout
from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import MOTORAPI_URL, SIGNAL_NEW_PLATE, SIGNAL_UPDATE
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
        frigate_url: str = "",
        frigate_token: str = "",
        verify_ssl: bool = True,
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
        self.frigate_url = frigate_url.rstrip("/")
        self.frigate_token = frigate_token
        self.verify_ssl = verify_ssl
        self.snapshot_dir = Path(hass.config.path(".storage", "frigate_lpr_snapshots"))
        self.store = Store(hass, STORAGE_VERSION, f"frigate_lpr.{entry_id}")
        self.registry = LPRRegistry(frequent_observations=frequent_observations, frequent_days=frequent_days)
        self.unsubscribe: Callable[[], None] | None = None

    async def async_setup(self) -> None:
        stored = await self.store.async_load()
        if stored:
            self.registry = LPRRegistry(
                stored,
                frequent_observations=self.frequent_observations,
                frequent_days=self.frequent_days,
            )
        self.unsubscribe = await mqtt.async_subscribe(self.hass, self.topic, self._message_received, qos=0)

    async def async_unload(self) -> None:
        if self.unsubscribe:
            self.unsubscribe()
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
            is_new_plate = bool(normalized_plate and normalized_plate not in self.registry.plates)
            changed = self.registry.observe(
                plate,
                timestamp,
                str(payload.get("id", "")),
                camera=str(payload.get("camera", "")),
                score=payload.get("score"),
                frigate_name=payload.get("name"),
            )
            if not changed:
                return
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
            if (
                self.snapshots_enabled
                and self.frigate_url
                and normalized_plate
                and payload.get("id")
            ):
                self.hass.async_create_task(
                    self._async_store_snapshot(
                        normalized_plate,
                        str(payload["id"]),
                        str(payload.get("camera", "")),
                    ),
                    "Frigate LPR snapshot",
                )
            async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            _LOGGER.warning("Ignored invalid Frigate LPR payload", exc_info=True)

    async def async_set_metadata(
        self,
        plate: str,
        name: str,
        category: str,
        *,
        notes: str | None = None,
        vehicle: dict[str, Any] | None = None,
        ignored: bool | None = None,
    ) -> None:
        is_new = normalize_plate(plate) not in self.registry.plates
        key = self.registry.set_metadata(
            plate,
            name,
            category,
            notes=notes,
            vehicle=vehicle,
            ignored=ignored,
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
    ) -> bool:
        """Update one passage persistently."""
        changed = self.registry.update_observation(
            plate, event_id, timestamp, camera, score
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

    async def _async_store_snapshot(self, plate: str, event_id: str, camera: str) -> None:
        """Fetch the event snapshot and retain the latest image for one case."""
        headers = {"Accept": "image/jpeg"}
        if self.frigate_token:
            headers["Authorization"] = f"Bearer {self.frigate_token}"
        url = f"{self.frigate_url}/api/events/{quote(event_id, safe='')}/snapshot.jpg"
        try:
            session = async_get_clientsession(self.hass, verify_ssl=self.verify_ssl)
            image: bytes | None = None
            for delay in (2, 5, 10):
                await asyncio.sleep(delay)
                response = await session.get(
                    url,
                    headers=headers,
                    params={"quality": 82},
                    timeout=ClientTimeout(total=20),
                )
                async with response:
                    if response.status == 200:
                        image = await response.read()
                        break
                    if response.status not in {404, 422}:
                        _LOGGER.warning("Frigate snapshot returned HTTP %s", response.status)
                        return
            if not image or len(image) > 8 * 1024 * 1024:
                _LOGGER.warning("Frigate snapshot was unavailable, empty or oversized")
                return
            await self.hass.async_add_executor_job(self._write_snapshot, plate, image)
            record = self.registry.plates.get(plate)
            if record is None:
                return
            record["snapshot"] = {
                "event_id": event_id,
                "captured_at": dt_util.utcnow().isoformat(),
                "camera": camera,
            }
            await self.store.async_save(self.registry.data)
            async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")
        except (ClientError, TimeoutError, OSError):
            _LOGGER.warning("Unable to store Frigate snapshot", exc_info=True)

    def _write_snapshot(self, plate: str, image: bytes) -> None:
        """Write a snapshot atomically outside the event loop."""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        target = self.snapshot_dir / f"{normalize_plate(plate)}.jpg"
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(image)
        temporary.replace(target)

    async def async_snapshot_bytes(self, plate: str) -> bytes | None:
        """Read a locally retained snapshot for the authenticated HTTP view."""
        return await self.hass.async_add_executor_job(self._read_snapshot, plate)

    def _read_snapshot(self, plate: str) -> bytes | None:
        """Read a snapshot outside the event loop."""
        path = self.snapshot_dir / f"{normalize_plate(plate)}.jpg"
        if not path.is_file():
            return None
        return path.read_bytes()

    @staticmethod
    def _vehicle_data(payload: dict[str, Any]) -> dict[str, Any]:
        """Keep all master data returned by the MotorAPI vehicle endpoint."""
        return {key: value for key, value in payload.items() if value is not None}
