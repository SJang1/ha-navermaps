"""Support for Naver Maps sensors."""
import asyncio
import requests
import logging
import hashlib
from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr
from homeassistant.const import UnitOfTime
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

DOMAIN = "ha-navermaps"
SCAN_INTERVAL = timedelta(minutes=10) 


class NaverMapsApiClient:
    def __init__(self, api_key_id: str, api_key: str, hass: HomeAssistant | None = None):
        self.rs = requests.Session()
        self.api_key_id = api_key_id
        self.api_key = api_key
        self.rs.headers.update({
            "x-ncp-apigw-api-key-id": api_key_id,
            "x-ncp-apigw-api-key": api_key
        })
        _LOGGER.debug(f"NaverMapsApiClient initialized with api_key_id: {api_key_id[:10] if api_key_id else 'EMPTY'}")
        self._hass = hass
        
        # Use shared geocode cache from hass.data (persists across updates)
        # Only for text addresses, not for entity locations
        if hass and DOMAIN in hass.data and "geocode_cache" in hass.data[DOMAIN]:
            self._geocode_cache = hass.data[DOMAIN]["geocode_cache"]
        else:
            self._geocode_cache = {}

    def direction(self, start: str, end: str, waypoints: list | str | None = None, priority: str = "traoptimal"):
        try:
            start_point = self.address(start)
            if not start_point:
                _LOGGER.error(f"Could not find address for start: {start}")
                return None
                
            _start = f"{start_point.get('x')},{start_point.get('y')}"
            _LOGGER.debug(f"Start point: {_start}")
            
            end_point = self.address(end)
            if not end_point:
                _LOGGER.error(f"Could not find address for end: {end}")
                return None
                
            _end = f"{end_point.get('x')},{end_point.get('y')}"
            _LOGGER.debug(f"End point: {_end}")
            
            # Handle waypoints (can be list or single string for backwards compatibility)
            _waypoints_str = None
            if waypoints:
                waypoint_list = waypoints if isinstance(waypoints, list) else [waypoints]
                waypoint_coords = []
                for wp in waypoint_list:
                    if wp:
                        wp_point = self.address(wp)
                        if wp_point:
                            waypoint_coords.append(f"{wp_point.get('x')},{wp_point.get('y')}")
                if waypoint_coords:
                    # Naver API uses | to separate multiple waypoints
                    _waypoints_str = "|".join(waypoint_coords)
                    _LOGGER.debug(f"Waypoints: {_waypoints_str}")

            params = {
                "start": _start,
                "goal": _end,
                "option": priority,
            }
            
            if _waypoints_str:
                params["waypoints"] = _waypoints_str

            _LOGGER.debug(f"Direction API call with params: {params}")
            resp = self.rs.get("https://maps.apigw.ntruss.com/map-direction/v1/driving", params=params)
            
            if resp.status_code != 200:
                _LOGGER.error(f"Direction API error: {resp.status_code} - {resp.text}")
                return None
            
            data = resp.json()
            _LOGGER.debug(f"Direction API response: {data}")
            
            if data.get("code") != 0:
                _LOGGER.error(f"API error code: {data.get('code')} - {data.get('message')}")
                return None
                
            return data
        except Exception as e:
            _LOGGER.error(f"Error getting directions: {e}")
            return None

    def address(self, query):
        if not query:
            return None
        
        # Check if it's a device tracker/person/zone entity
        # These are NOT cached because their location can change
        if query.startswith(("device_tracker.", "person.", "zone.", "sensor.")):
            location = self._get_entity_location(query)
            if location:
                return location
            # If entity lookup fails, don't try to look it up as address
            return None
        
        # For text addresses, use persistent geocode cache
        if query in self._geocode_cache:
            _LOGGER.debug(f"Using cached geocode for: {query}")
            return self._geocode_cache[query]
            
        try:
            resp = self.rs.get("https://maps.apigw.ntruss.com/map-geocode/v2/geocode", params={
                "query": query
            })

            if resp.status_code != 200:
                _LOGGER.warning(f"Address lookup failed for: {query}")
                return None
            
            data = resp.json()
            addresses = data.get("addresses", [])
            
            if len(addresses) == 0:
                _LOGGER.warning(f"Address lookup failed for: {query}")
                return None
            
            result = {
                "x": addresses[0].get("x"),
                "y": addresses[0].get("y")
            }
            # Save to persistent cache
            self._geocode_cache[query] = result
            _LOGGER.info(f"Cached geocode for address: {query} -> ({result['x']}, {result['y']})")
            return result
        except Exception as e:
            _LOGGER.error(f"Error looking up address {query}: {e}")
            return None
    
    def _get_entity_location(self, entity_id: str):
        """Get location from a Home Assistant entity (device_tracker, person, zone)."""
        if not self._hass:
            return None
        
        try:
            state = self._hass.states.get(entity_id)
            if not state:
                _LOGGER.error(f"Entity not found: {entity_id}")
                return None
            
            # Get latitude and longitude from entity attributes
            latitude = state.attributes.get("latitude")
            y = state.attributes.get("y")
            
            longitude = state.attributes.get("longitude")
            x = state.attributes.get("x")
            
            if latitude is not None and longitude is not None:
                return {
                    "x": str(longitude),
                    "y": str(latitude)
                }
            elif x is not None and y is not None:
                return {
                    "x": str(x),
                    "y": str(y)
                }
            else:
                _LOGGER.error(f"No location data for entity: {entity_id}")
                return None
                
        except Exception as e:
            _LOGGER.error(f"Error getting entity location {entity_id}: {e}")
            return None
    
    def reverse_geocode(self, longitude: float, latitude: float, orders: str = "roadaddr,addr"):
        """
        Convert coordinates to address information using reverse geocoding.
        
        Args:
            longitude: Longitude (X coordinate)
            latitude: Latitude (Y coordinate)
            orders: Conversion types, comma-separated. Options: legalcode, admcode, addr, roadaddr
                   Default: "roadaddr,addr" (road address and land address)
        
        Returns:
            dict: Response data with address information, or None on error
        """
        try:
            params = {
                "coords": f"{longitude},{latitude}",
                "output": "json",
                "orders": orders
            }
            
            resp = self.rs.get(
                "https://maps.apigw.ntruss.com/map-reversegeocode/v2/gc",
                params=params
            )
            
            if resp.status_code != 200:
                _LOGGER.error(f"Reverse geocoding API error: {resp.status_code} - {resp.text}")
                return None
            
            data = resp.json()
            
            if data.get("status", {}).get("code") != 0:
                _LOGGER.error(f"Reverse geocoding error: {data.get('status', {}).get('message')}")
                return None
            
            return data
            
        except Exception as e:
            _LOGGER.error(f"Error in reverse geocoding: {e}")
            return None
    
    def get_address_from_coords(self, longitude: float, latitude: float):
        """
        Get formatted address string from coordinates.
        
        Args:
            longitude: Longitude (X coordinate)
            latitude: Latitude (Y coordinate)
        
        Returns:
            dict: Contains 'road_address' and 'land_address', or None on error
        """
        data = self.reverse_geocode(longitude, latitude, "roadaddr,addr")
        
        if not data or not data.get("results"):
            return None
        
        result: dict[str, str | None] = {
            "road_address": None,
            "land_address": None,
            "area1": None,  # Province/City (시/도)
            "area2": None,  # District/County (시/군/구)
            "area3": None,  # Town/Neighborhood (읍/면/동)
            "area4": None,  # Village (리)
        }
        
        for item in data.get("results", []):
            name = item.get("name")
            region = item.get("region", {})
            land = item.get("land", {})
            
            # Extract area information
            if region:
                if region.get("area1", {}).get("name"):
                    result["area1"] = region["area1"]["name"]
                if region.get("area2", {}).get("name"):
                    result["area2"] = region["area2"]["name"]
                if region.get("area3", {}).get("name"):
                    result["area3"] = region["area3"]["name"]
                if region.get("area4", {}).get("name"):
                    result["area4"] = region["area4"]["name"]
            
            if name == "roadaddr":
                # Build road address
                parts = []
                if result["area1"]:
                    parts.append(result["area1"])
                if result["area2"]:
                    parts.append(result["area2"])
                if result["area3"]:
                    parts.append(result["area3"])
                if land.get("name"):  # Road name
                    parts.append(land["name"])
                if land.get("number1"):
                    parts.append(land["number1"])
                
                result["road_address"] = " ".join(parts) if parts else None
                
            elif name == "addr":
                # Build land address
                parts = []
                if result["area1"]:
                    parts.append(result["area1"])
                if result["area2"]:
                    parts.append(result["area2"])
                if result["area3"]:
                    parts.append(result["area3"])
                if result["area4"]:
                    parts.append(result["area4"])
                
                # Add lot number
                number1 = land.get("number1", "")
                number2 = land.get("number2", "")
                if number1:
                    if number2:
                        parts.append(f"{number1}-{number2}")
                    else:
                        parts.append(number1)
                
                result["land_address"] = " ".join(parts) if parts else None
        
        return result


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Naver Maps sensors from a config entry."""
    api_key_id = config_entry.data.get("api_key_id") or ""
    api_key = config_entry.data.get("api_key") or ""
    
    _LOGGER.info(f"API Key ID: {api_key_id[:10] if api_key_id else 'EMPTY'}...")
    _LOGGER.info(f"API Key: {api_key[:10] if api_key else 'EMPTY'}...")
    
    routes = config_entry.options.get("routes", {})
    scan_interval = config_entry.options.get("scan_interval", 10)
    
    _LOGGER.info(f"Setting up Naver Maps with {len(routes)} routes: {list(routes.keys())}")
    
    # Create device for this integration
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, config_entry.entry_id)},
        name="Naver Maps",
        manufacturer="Naver",
        model="Maps API",
    )
    
    entities = []
    for route_id, route_data in routes.items():
        # Support both old 'waypoint' (single) and new 'waypoints' (list) format
        waypoints = route_data.get("waypoints", [])
        if not waypoints and route_data.get("waypoint"):
            waypoints = [route_data.get("waypoint")]
        
        _LOGGER.info(f"Creating sensor for route {route_id}: {route_data.get('start')} -> {route_data.get('end')} (waypoints: {len(waypoints)})")
        entities.append(
            NaverMapsEta(
                api_key_id=api_key_id,
                api_key=api_key,
                route_id=route_id,
                start=route_data.get("start"),
                end=route_data.get("end"),
                waypoints=waypoints,
                priority=route_data.get("priority", "traoptimal"),
                entry_id=config_entry.entry_id,
                route_name=route_data.get("name"),
                scan_interval_minutes=scan_interval,
            )
        )
    
    async_add_entities(entities, False)
    
    # Log location details in background
    async def log_location_details():
        """Log route location details asynchronously."""
        await asyncio.sleep(1)  # Wait for first update
        temp_client = NaverMapsApiClient(api_key_id, api_key, hass)
        
        for route_id, route_data in routes.items():
            start_str = route_data.get('start')
            end_str = route_data.get('end')
            
            start_info = start_str
            end_info = end_str
            
            # Run blocking calls in executor
            def get_location_info():
                try:
                    start_loc = temp_client.address(start_str)
                    end_loc = temp_client.address(end_str)
                    
                    s_info = f"{start_str}"
                    e_info = f"{end_str}"
                    
                    if start_loc:
                        coords_info = f"x={start_loc.get('x')}, y={start_loc.get('y')}"
                        if start_str.startswith(("device_tracker.", "person.", "zone.", "sensor.")):
                            try:
                                x = float(start_loc.get('x', 0))
                                y = float(start_loc.get('y', 0))
                                addr_data = temp_client.get_address_from_coords(x, y)
                                if addr_data and addr_data.get('road_address'):
                                    s_info = f"{start_str} [{addr_data.get('road_address')}] ({coords_info})"
                                else:
                                    s_info = f"{start_str} ({coords_info})"
                            except (ValueError, TypeError):
                                s_info = f"{start_str} ({coords_info})"
                        else:
                            s_info = f"{start_str} ({coords_info})"
                    
                    if end_loc:
                        coords_info = f"x={end_loc.get('x')}, y={end_loc.get('y')}"
                        if end_str.startswith(("device_tracker.", "person.", "zone.", "sensor.")):
                            try:
                                x = float(end_loc.get('x', 0))
                                y = float(end_loc.get('y', 0))
                                addr_data = temp_client.get_address_from_coords(x, y)
                                if addr_data and addr_data.get('road_address'):
                                    e_info = f"{end_str} [{addr_data.get('road_address')}] ({coords_info})"
                                else:
                                    e_info = f"{end_str} ({coords_info})"
                            except (ValueError, TypeError):
                                e_info = f"{end_str} ({coords_info})"
                        else:
                            e_info = f"{end_str} ({coords_info})"
                    
                    return route_id, s_info, e_info
                except Exception as e:
                    _LOGGER.error(f"Error getting location info: {e}")
                    return route_id, start_str, end_str
            
            route_id, start_info, end_info = await hass.async_add_executor_job(get_location_info)
            _LOGGER.info(f"Route {route_id}: {start_info} -> {end_info}")
    
    hass.async_create_task(log_location_details())


class NaverMapsEta(SensorEntity):
    """Representation of a Naver Maps ETA sensor."""

    def __init__(self, api_key_id, api_key, route_id, start, end, waypoints, priority, entry_id, route_name=None, scan_interval_minutes=10):
        """Initialize the sensor."""
        self._route_id = route_id
        self._start = start
        self._end = end
        # Support both list and single waypoint for backwards compatibility
        if isinstance(waypoints, list):
            self._waypoints = [wp for wp in waypoints if wp]
        elif waypoints:
            self._waypoints = [waypoints]
        else:
            self._waypoints = []
        self._priority = priority
        self._api_key_id = api_key_id
        self._api_key = api_key
        self._entry_id = entry_id
        self._hass = None
        self._custom_name = route_name
        self._scan_interval_minutes = scan_interval_minutes
        
        # Create name
        if route_name:
            self._attr_name = route_name
        else:
            route_name_auto = f"{start} to {end}"
            if self._waypoints:
                if len(self._waypoints) == 1:
                    route_name_auto += f" via {self._waypoints[0]}"
                else:
                    route_name_auto += f" ({len(self._waypoints)} waypoints)"
            self._attr_name = route_name_auto
        
        # Create unique ID
        unique_string = f"{entry_id}_{route_id}"
        self._attr_unique_id = hashlib.md5(unique_string.encode("UTF-8")).hexdigest()
        
        # Initialize all required entity attributes
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}
        self._attr_native_unit_of_measurement = UnitOfTime.MINUTES
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:map-marker-distance"
        self._attr_has_entity_name = False
        self._last_update = None
        
        # Device info for grouping
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Naver Maps",
            "manufacturer": "Naver",
            "model": "Maps API",
        }
        
        _LOGGER.debug(f"NaverMapsEta initialized: {self._attr_unique_id}")
    
    async def async_added_to_hass(self):
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._hass = self.hass
        # Update name immediately with friendly names
        self._update_friendly_name()
        _LOGGER.debug(f"Entity added: {self.entity_id}, unique_id: {self.unique_id}")
        
        # Schedule immediate update on startup
        self.async_schedule_update_ha_state(force_refresh=True)
        
        # Schedule periodic updates with custom interval
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self.async_update_custom,
                timedelta(minutes=self._scan_interval_minutes)
            )
        )
    
    async def async_update_custom(self, now=None):
        """Async wrapper for update."""
        await self.hass.async_add_executor_job(self.update)
    
    def _get_friendly_name(self, location: str) -> str:
        """Get friendly name for entity ID or return location as is."""
        if not self._hass or not location:
            return location
        
        # Check if it's an entity ID
        if location.startswith(("device_tracker.", "person.", "zone.", "sensor.")):
            try:
                state = self._hass.states.get(location)
                if state:
                    # Try different attributes for friendly name
                    friendly_name = state.attributes.get("friendly_name")
                    if friendly_name:
                        return friendly_name
                    # For person entities, try getting name from entity registry
                    if location.startswith("person."):
                        from homeassistant.helpers import entity_registry as er
                        registry = er.async_get(self._hass)
                        entity_entry = registry.async_get(location)
                        if entity_entry and entity_entry.name:
                            return entity_entry.name
                    # Fallback to state.name
                    if hasattr(state, 'name') and state.name:
                        return state.name
            except Exception as e:
                _LOGGER.debug(f"Error getting friendly name for {location}: {e}")
        
        return location
    
    def _update_friendly_name(self):
        """Update sensor name with friendly names."""
        try:
            # If custom name is set, don't override it
            if self._custom_name:
                return
            
            if not self._hass:
                return
            
            start_name = self._get_friendly_name(self._start)
            end_name = self._get_friendly_name(self._end)
            
            route_name = f"{start_name} to {end_name}"
            if self._waypoints:
                if len(self._waypoints) == 1:
                    waypoint_name = self._get_friendly_name(self._waypoints[0])
                    route_name += f" via {waypoint_name}"
                else:
                    waypoint_names = [self._get_friendly_name(wp) for wp in self._waypoints]
                    route_name += f" via {', '.join(waypoint_names)}"
            
            self._attr_name = route_name
        except Exception as e:
            _LOGGER.debug(f"Error updating friendly name: {e}")

    @property
    def available(self):
        """Return True if entity is available."""
        return self._attr_native_value is not None

    def update(self):
        """Fetch new state data for the sensor."""
        _LOGGER.info(f"Updating sensor {self._route_id}...")
        try:
            # Update friendly name before fetching data
            self._update_friendly_name()
            
            client = NaverMapsApiClient(self._api_key_id, self._api_key, self._hass)
            result = client.direction(
                self._start,
                self._end,
                self._waypoints if self._waypoints else None,
                self._priority
            )
            
            _LOGGER.debug(f"Direction result for {self._route_id}: {result}")
            
            if result and result.get("code") == 0 and result.get("route"):
                # Naver Maps returns route.{option} where option is the priority
                routes = result.get("route", {}).get(self._priority, [])
                if routes:
                    data = routes[0]
                    summary = data.get("summary", {})
                    
                    # Update last update time
                    self._last_update = datetime.now()
                    
                    # Duration in milliseconds, convert to minutes
                    duration_ms = summary.get("duration", 0)
                    self._attr_native_value = round(duration_ms / 1000 / 60, 1)
                    
                    # Additional attributes
                    self._attr_extra_state_attributes = {
                        "distance": round(summary.get("distance", 0) / 1000, 2),  # km
                        "distance_unit": "km",
                        "duration_seconds": round(duration_ms / 1000),
                        "start": self._start,
                        "end": self._end,
                        "waypoints": self._waypoints if self._waypoints else None,
                        "waypoint_count": len(self._waypoints),
                        "priority": self._priority,
                        "toll_fare": summary.get("tollFare", 0),
                        "taxi_fare": summary.get("taxiFare", 0),
                        "fuel_price": summary.get("fuelPrice", 0),
                        "last_update": self._last_update.strftime("%Y-%m-%d %H:%M:%S") if self._last_update else None,
                        "minutes_since_update": round((datetime.now() - self._last_update).total_seconds() / 60) if self._last_update else None,
                    }
                else:
                    _LOGGER.warning(f"No route data for {self._attr_name}")
                    self._attr_native_value = None
            else:
                _LOGGER.warning(f"No route data for {self._attr_name}: {result}")
        except Exception as e:
            _LOGGER.error(f"Error updating {self._attr_name}: {e}")
            self._attr_native_value = None
