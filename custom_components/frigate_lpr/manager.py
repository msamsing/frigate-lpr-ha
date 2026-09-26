"""MQTT and persistence manager."""

from __future__ import annotations

from datetime import datetime
import json
import logging
from typing import Any, Callable

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import SIGNAL_NEW_PLATE, SIGNAL_UPDATE
from .model import LPRRegistry, normalize_plate

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1


class LPRManager:
    def __init__(self, hass: HomeAssistant, entry_id: str, topic: str, camera: str, frequent_observations: int, frequent_days: int) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.topic = topic
        self.camera = camera
        self.store = Store(hass, STORAGE_VERSION, f"frigate_lpr.{entry_id}")
        self.registry = LPRRegistry(frequent_observations=frequent_observations, frequent_days=frequent_days)
        self.unsubscribe: Callable[[], None] | None = None

    async def async_setup(self) -> None:
        stored = await self.store.async_load()
        if stored:
            self.registry.data = stored
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
                    {"plate": normalized_plate, "camera": payload.get("camera", ""), "timestamp": timestamp.isoformat()},
                )
            async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            _LOGGER.warning("Ignored invalid Frigate LPR payload", exc_info=True)

    async def async_set_metadata(self, plate: str, name: str, category: str) -> None:
        is_new = normalize_plate(plate) not in self.registry.plates
        key = self.registry.set_metadata(plate, name, category)
        await self.store.async_save(self.registry.data)
        if is_new:
            async_dispatcher_send(self.hass, f"{SIGNAL_NEW_PLATE}_{self.entry_id}", key)
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")

    async def async_remove_metadata(self, plate: str) -> None:
        self.registry.remove_metadata(plate)
        await self.store.async_save(self.registry.data)
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry_id}")
