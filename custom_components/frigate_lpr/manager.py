"""MQTT and persistence manager."""

from __future__ import annotations

from datetime import datetime
import json
import logging
from typing import Any, Callable

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
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.topic = topic
        self.camera = camera
        self.frequent_observations = frequent_observations
        self.frequent_days = frequent_days
        self.motorapi_enabled = motorapi_enabled
        self.motorapi_key = motorapi_key
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
    ) -> None:
        is_new = normalize_plate(plate) not in self.registry.plates
        key = self.registry.set_metadata(
            plate,
            name,
            category,
            notes=notes,
            vehicle=vehicle,
        )
        await self.store.async_save(self.registry.data)
        if is_new:
            async_dispatcher_send(self.hass, f"{SIGNAL_NEW_PLATE}_{self.entry_id}", key)
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")

    async def async_remove_metadata(self, plate: str) -> None:
        self.registry.remove_metadata(plate)
        await self.store.async_save(self.registry.data)
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")

    async def _async_lookup_vehicle(self, plate: str) -> None:
        """Look up and permanently cache one new, unknown plate."""
        record = self.registry.plates.get(plate, {})
        if record.get("name") or record.get("category") in {"own", "known"}:
            self.registry.mark_vehicle_lookup(
                plate,
                {
                    "status": "skipped_private",
                    "provider": "motorapi",
                    "attempted_at": dt_util.utcnow().isoformat(),
                },
            )
            await self.store.async_save(self.registry.data)
            return

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
                            "vehicle": self._vehicle_fields(payload),
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

    @staticmethod
    def _vehicle_fields(payload: dict[str, Any]) -> dict[str, Any]:
        """Keep only display fields required by the integration."""
        fields = (
            "make",
            "model",
            "variant",
            "model_type",
            "model_year",
            "color",
            "chassis_type",
            "fuel_type",
            "type",
        )
        return {field: payload[field] for field in fields if payload.get(field) is not None}
