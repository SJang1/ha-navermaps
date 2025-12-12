"""The Naver Maps integration."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

_LOGGER = logging.getLogger(__name__)

DOMAIN = "ha-navermaps"
PLATFORMS = [Platform.SENSOR]
GEOCODE_CACHE_KEY = "geocode_cache"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Naver Maps from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data
    
    # Initialize shared geocode cache (persists across sensor updates)
    if GEOCODE_CACHE_KEY not in hass.data[DOMAIN]:
        hass.data[DOMAIN][GEOCODE_CACHE_KEY] = {}
        _LOGGER.debug("Initialized geocode cache")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
