"""Init file for Supervisor Home Assistant RESTful API."""

import asyncio
from collections.abc import Awaitable
import logging
from typing import Any

from aiohttp import web
import voluptuous as vol

from ..const import (
    ATTR_ARCH,
    ATTR_AUDIO_INPUT,
    ATTR_AUDIO_OUTPUT,
    ATTR_BACKUP,
    ATTR_BACKUPS_EXCLUDE_DATABASE,
    ATTR_BLK_READ,
    ATTR_BLK_WRITE,
    ATTR_BOOT,
    ATTR_CPU_PERCENT,
    ATTR_IMAGE,
    ATTR_IP_ADDRESS,
    ATTR_MACHINE,
    ATTR_MEMORY_LIMIT,
    ATTR_MEMORY_PERCENT,
    ATTR_MEMORY_USAGE,
    ATTR_NETWORK_RX,
    ATTR_NETWORK_TX,
    ATTR_PORT,
    ATTR_REFRESH_TOKEN,
    ATTR_SSL,
    ATTR_UPDATE_AVAILABLE,
    ATTR_VERSION,
    ATTR_VERSION_LATEST,
    ATTR_WATCHDOG,
)
from ..coresys import CoreSysAttributes
from ..exceptions import APIDBMigrationInProgress, APIError
from ..validate import docker_image, network_port, version_tag
from .const import ATTR_FORCE, ATTR_SAFE_MODE
from .utils import api_process, api_validate

_LOGGER: logging.Logger = logging.getLogger(__name__)

# pylint: disable=no-value-for-parameter
SCHEMA_OPTIONS = vol.Schema(
    {
        vol.Optional(ATTR_BOOT): vol.Boolean(),
        vol.Optional(ATTR_IMAGE): vol.Maybe(docker_image),
        vol.Optional(ATTR_PORT): network_port,
        vol.Optional(ATTR_SSL): vol.Boolean(),
        vol.Optional(ATTR_WATCHDOG): vol.Boolean(),
        vol.Optional(ATTR_REFRESH_TOKEN): vol.Maybe(str),
        vol.Optional(ATTR_AUDIO_OUTPUT): vol.Maybe(str),
        vol.Optional(ATTR_AUDIO_INPUT): vol.Maybe(str),
        vol.Optional(ATTR_BACKUPS_EXCLUDE_DATABASE): vol.Boolean(),
    }
)

SCHEMA_UPDATE = vol.Schema(
    {
        vol.Optional(ATTR_VERSION): version_tag,
        vol.Optional(ATTR_BACKUP): bool,
    }
)

SCHEMA_RESTART = vol.Schema(
    {
        vol.Optional(ATTR_SAFE_MODE, default=False): vol.Boolean(),
        vol.Optional(ATTR_FORCE, default=False): vol.Boolean(),
    }
)

SCHEMA_STOP = vol.Schema(
    {
        vol.Optional(ATTR_FORCE, default=False): vol.Boolean(),
    }
)


class APIHomeAssistant(CoreSysAttributes):
    """Handle RESTful API for Home Assistant functions."""

    async def _check_offline_migration(self, force: bool = False) -> None:
        """Check and raise if there's an offline DB migration in progress."""
        if (
            not force
            and (state := await self.sys_homeassistant.api.get_api_state())
            and state.offline_db_migration
        ):
            raise APIDBMigrationInProgress(
                "Offline database migration in progress, try again after it has completed"
            )

    @api_process
    async def info(self, request: web.Request) -> dict[str, Any]:
        """Return host information."""
        return {
            ATTR_VERSION: self.sys_homeassistant.version,
            ATTR_VERSION_LATEST: self.sys_homeassistant.latest_version,
            ATTR_UPDATE_AVAILABLE: self.sys_homeassistant.need_update,
            ATTR_MACHINE: self.sys_homeassistant.machine,
            ATTR_IP_ADDRESS: str(self.sys_homeassistant.ip_address),
            ATTR_ARCH: self.sys_homeassistant.arch,
            ATTR_IMAGE: self.sys_homeassistant.image,
            ATTR_BOOT: self.sys_homeassistant.boot,
            ATTR_PORT: self.sys_homeassistant.api_port,
            ATTR_SSL: self.sys_homeassistant.api_ssl,
            ATTR_WATCHDOG: self.sys_homeassistant.watchdog,
            ATTR_AUDIO_INPUT: self.sys_homeassistant.audio_input,
            ATTR_AUDIO_OUTPUT: self.sys_homeassistant.audio_output,
            ATTR_BACKUPS_EXCLUDE_DATABASE: self.sys_homeassistant.backups_exclude_database,
        }

    @api_process
    async def options(self, request: web.Request) -> None:
        """Set Home Assistant options."""
        body = await api_validate(SCHEMA_OPTIONS, request)

        if ATTR_IMAGE in body:
            self.sys_homeassistant.set_image(body[ATTR_IMAGE])
            self.sys_homeassistant.override_image = (
                self.sys_homeassistant.image != self.sys_homeassistant.default_image
            )

        if ATTR_BOOT in body:
            self.sys_homeassistant.boot = body[ATTR_BOOT]

        if ATTR_PORT in body:
            self.sys_homeassistant.api_port = body[ATTR_PORT]

        if ATTR_SSL in body:
            self.sys_homeassistant.api_ssl = body[ATTR_SSL]

        if ATTR_WATCHDOG in body:
            self.sys_homeassistant.watchdog = body[ATTR_WATCHDOG]

        if ATTR_REFRESH_TOKEN in body:
            self.sys_homeassistant.refresh_token = body[ATTR_REFRESH_TOKEN]

        if ATTR_AUDIO_INPUT in body:
            self.sys_homeassistant.audio_input = body[ATTR_AUDIO_INPUT]

        if ATTR_AUDIO_OUTPUT in body:
            self.sys_homeassistant.audio_output = body[ATTR_AUDIO_OUTPUT]

        if ATTR_BACKUPS_EXCLUDE_DATABASE in body:
            self.sys_homeassistant.backups_exclude_database = body[
                ATTR_BACKUPS_EXCLUDE_DATABASE
            ]

        await self.sys_homeassistant.save_data()

    @api_process
    async def stats(self, request: web.Request) -> dict[Any, str]:
        """Return resource information."""
        stats = await self.sys_homeassistant.core.stats()
        if not stats:
            raise APIError("No stats available")

        return {
            ATTR_CPU_PERCENT: stats.cpu_percent,
            ATTR_MEMORY_USAGE: stats.memory_usage,
            ATTR_MEMORY_LIMIT: stats.memory_limit,
            ATTR_MEMORY_PERCENT: stats.memory_percent,
            ATTR_NETWORK_RX: stats.network_rx,
            ATTR_NETWORK_TX: stats.network_tx,
            ATTR_BLK_READ: stats.blk_read,
            ATTR_BLK_WRITE: stats.blk_write,
        }

    @api_process
    async def update(self, request: web.Request) -> None:
        """Update Home Assistant."""
        body = await api_validate(SCHEMA_UPDATE, request)
        await self._check_offline_migration()

        await asyncio.shield(
            self.sys_homeassistant.core.update(
                version=body.get(ATTR_VERSION, self.sys_homeassistant.latest_version),
                backup=body.get(ATTR_BACKUP),
            )
        )

    @api_process
    async def stop(self, request: web.Request) -> Awaitable[None]:
        """Stop Home Assistant."""
        body = await api_validate(SCHEMA_STOP, request)
        await self._check_offline_migration(force=body[ATTR_FORCE])

        return await asyncio.shield(self.sys_homeassistant.core.stop())

    @api_process
    def start(self, request: web.Request) -> Awaitable[None]:
        """Start Home Assistant."""
        return asyncio.shield(self.sys_homeassistant.core.start())

    @api_process
    async def restart(self, request: web.Request) -> None:
        """Restart Home Assistant."""
        body = await api_validate(SCHEMA_RESTART, request)
        await self._check_offline_migration(force=body[ATTR_FORCE])

        await asyncio.shield(
            self.sys_homeassistant.core.restart(safe_mode=body[ATTR_SAFE_MODE])
        )

    @api_process
    async def rebuild(self, request: web.Request) -> None:
        """Rebuild Home Assistant."""
        body = await api_validate(SCHEMA_RESTART, request)
        await self._check_offline_migration(force=body[ATTR_FORCE])

        await asyncio.shield(
            self.sys_homeassistant.core.rebuild(safe_mode=body[ATTR_SAFE_MODE])
        )

    @api_process
    async def check(self, request: web.Request) -> None:
        """Check configuration of Home Assistant."""
        result = await self.sys_homeassistant.core.check_config()
        if not result.valid:
            raise APIError(result.log)
