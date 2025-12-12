import logging
import asyncio
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

DOMAIN = "ha-navermaps"
MAX_WAYPOINTS = 5


class NaverMapsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Naver Maps."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Validate API keys
            api_key_id = user_input.get("X-NCP-APIGW-API-KEY-ID", "").strip()
            api_key = user_input.get("X-NCP-APIGW-API-KEY", "").strip()
            
            # Validate that credentials are not empty
            if not api_key_id or not api_key:
                errors["base"] = "invalid_auth"
            else:
                # Create unique ID based on API key ID
                await self.async_set_unique_id(api_key_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Naver Maps",
                    data={
                        "api_key_id": api_key_id,
                        "api_key": api_key,
                    },
                    options={
                        "routes": {},
                        "scan_interval": 10,  # Default scan interval
                    }
                )

        data_schema = vol.Schema({
            vol.Required("X-NCP-APIGW-API-KEY-ID"): str,
            vol.Required("X-NCP-APIGW-API-KEY"): str,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "info": "Enter your Naver Cloud Platform Maps API credentials. Get them from Naver Cloud Console."
            },
        )

    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfiguration of API credentials."""
        errors = {}
        config_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        
        # Safety check - should not happen but handle gracefully
        if not config_entry:
            return self.async_abort(reason="unknown")

        if user_input is not None:
            # Extract new API keys
            api_key_id = user_input.get("X-NCP-APIGW-API-KEY-ID", "").strip()
            api_key = user_input.get("X-NCP-APIGW-API-KEY", "").strip()
            
            # Validate that credentials are not empty
            if not api_key_id or not api_key:
                errors["base"] = "invalid_auth"
            else:
                # Check if new API Key ID conflicts with another entry
                # (but allow it if it's the same as current entry's unique_id)
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if entry.unique_id == api_key_id and entry.entry_id != config_entry.entry_id:
                        errors["base"] = "already_configured"
                        break
                
                if not errors:
                    # Update the config entry with new credentials while preserving other data
                    self.hass.config_entries.async_update_entry(
                        config_entry,
                        data={
                            **config_entry.data,  # Preserve existing data
                            "api_key_id": api_key_id,
                            "api_key": api_key,
                        },
                    )
                    
                    # If API Key ID changed, update the unique_id
                    if config_entry.unique_id != api_key_id:
                        self.hass.config_entries.async_update_entry(
                            config_entry,
                            unique_id=api_key_id,
                        )
                    
                    # Reload the integration to use new credentials
                    await self.hass.config_entries.async_reload(config_entry.entry_id)
                    
                    return self.async_abort(reason="reconfigure_successful")

        # Pre-fill with current values (masked for security)
        current_api_key_id = config_entry.data.get("api_key_id", "")
        current_api_key = config_entry.data.get("api_key", "")
        
        # Mask credentials for security (show only first 4 and last 4 characters)
        if len(current_api_key_id) > 8:
            masked_api_key_id = current_api_key_id[:4] + "..." + current_api_key_id[-4:]
        else:
            masked_api_key_id = "***" if current_api_key_id else ""
            
        if len(current_api_key) > 8:
            masked_api_key = current_api_key[:4] + "..." + current_api_key[-4:]
        else:
            masked_api_key = "***" if current_api_key else ""
        
        # Use empty defaults to avoid users having to clear masked values
        # Show masked values in description instead
        data_schema = vol.Schema({
            vol.Required("X-NCP-APIGW-API-KEY-ID"): str,
            vol.Required("X-NCP-APIGW-API-KEY"): str,
        })

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "info": "\n".join([
                    f"Current API Key ID: {masked_api_key_id}",
                    f"Current API Key: {masked_api_key}",
                    "",
                    "Enter your new Naver Cloud Platform Maps API credentials."
                ])
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return NaverMapsOptionsFlowHandler(config_entry)


class NaverMapsOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Naver Maps integration."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.routes = dict(config_entry.options.get("routes", {}))
        self.scan_interval = config_entry.options.get("scan_interval", 10)
        self.editing_route_id = None
        # Temporary storage for route being added/edited
        self._temp_route = {}
        self._temp_waypoints = []

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        return await self.async_step_route_list()

    async def async_step_route_list(self, user_input=None):
        """Show list of routes."""
        if user_input is not None:
            action = user_input.get("action")
            self.scan_interval = user_input.get("scan_interval", self.scan_interval)
            
            if action == "add":
                # Reset temp storage
                self._temp_route = {}
                self._temp_waypoints = []
                return await self.async_step_add_route()
            elif action.startswith("delete_"):
                route_id = action.replace("delete_", "")
                self.routes.pop(route_id, None)
                return await self.async_step_route_list()
            elif action == "save":
                # Log before saving
                _LOGGER.info(f"Saving routes: {self.routes}")
                # Update config entry options
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    options={
                        "routes": self.routes,
                        "scan_interval": self.scan_interval if hasattr(self, 'scan_interval') else self.config_entry.options.get("scan_interval", 1)
                    }
                )
                
                # Reload in background with proper error handling
                async def reload_integration():
                    try:
                        await asyncio.sleep(0.5)  # Brief delay to ensure options are saved
                        await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                    except Exception as e:
                        _LOGGER.error(f"Error reloading Naver Maps: {e}")
                
                self.hass.async_create_task(reload_integration())
                return self.async_abort(reason="")

        # Build list of routes with actions
        route_actions = {"add": "➕ 새 경로 추가", "save": "✅ 저장 후 종료"}
        
        # Show added routes as info (non-actionable)
        if self.routes:
            for route_id, route_data in self.routes.items():
                custom_name = route_data.get('name')
                start = route_data.get('start', 'Unknown')
                end = route_data.get('end', 'Unknown')
                
                if custom_name:
                    display_name = f"  • {custom_name}"
                else:
                    display_name = f"  • {start} → {end}"
                
                # Show waypoints count if any
                waypoints = route_data.get('waypoints', [])
                if waypoints:
                    display_name += f" (경유지 {len(waypoints)}개)"
                elif route_data.get('waypoint'):
                    display_name += f" (경유지 1개)"
                
                # Add delete option
                route_actions[f"delete_{route_id}"] = f"🗑️  {display_name}"
        
        _LOGGER.debug(f"Route list - routes in memory: {self.routes}")

        data_schema = vol.Schema({
            vol.Required("action"): vol.In(route_actions),
            vol.Optional("scan_interval", default=self.scan_interval): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=60,
                    unit_of_measurement="분",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        })

        return self.async_show_form(
            step_id="route_list",
            data_schema=data_schema,
        )

    async def async_step_add_route(self, user_input=None):
        """Add a new route - basic info."""
        errors = {}

        if user_input is not None:
            action = user_input.get("action")
            
            # Handle cancel/back action
            if action == "cancel":
                self._temp_route = {}
                self._temp_waypoints = []
                return await self.async_step_route_list()
            
            # Prefer entity selection over text input
            start = user_input.get("start_entity") or user_input.get("start", "")
            end = user_input.get("end_entity") or user_input.get("end", "")
            
            if not start or not end:
                errors["base"] = "missing_location"
            else:
                # Store basic info
                self._temp_route = {
                    "name": user_input.get("route_name", "").strip() or None,
                    "start": start,
                    "end": end,
                    "priority": user_input.get("priority", "traoptimal"),
                }
                self._temp_waypoints = []
                
                if action == "add_waypoint":
                    return await self.async_step_add_waypoint()
                elif action == "confirm":
                    return await self._save_route()

        data_schema = vol.Schema({
            vol.Optional("route_name"): selector.TextSelector(
                selector.TextSelectorConfig(
                    multiline=False,
                    type=selector.TextSelectorType.TEXT,
                )
            ),
            vol.Optional("start_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["device_tracker", "person", "zone"],
                )
            ),
            vol.Optional("start"): selector.TextSelector(
                selector.TextSelectorConfig(
                    multiline=False,
                    type=selector.TextSelectorType.TEXT,
                )
            ),
            vol.Optional("end_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["device_tracker", "person", "zone"],
                )
            ),
            vol.Optional("end"): selector.TextSelector(
                selector.TextSelectorConfig(
                    multiline=False,
                    type=selector.TextSelectorType.TEXT,
                )
            ),
            vol.Optional("priority", default="traoptimal"): vol.In({
                "traoptimal": "실시간 최적 (Optimal)",
                "trafast": "실시간 빠른 길 (Fastest)",
                "tracomfort": "실시간 편한 길 (Comfortable)",
                "traavoidtoll": "무료 우선 (Avoid Toll)",
                "traavoidcaronly": "자동차 전용 도로 회피 (Avoid Car-Only)",
            }),
            vol.Required("action"): vol.In({
                "cancel": "⬅️ 취소",
                "add_waypoint": "📍 경유지 추가",
                "confirm": "✅ 경로 저장",
            }),
        })

        return self.async_show_form(
            step_id="add_route",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "tip": "엔티티 선택, 주소 입력, 또는 좌표(경도,위도) 입력 가능. 예: 127.12345,37.12345"
            },
        )

    async def async_step_add_waypoint(self, user_input=None):
        """Add a waypoint to the route."""
        errors = {}
        current_count = len(self._temp_waypoints)
        
        if user_input is not None:
            action = user_input.get("action")
            
            if action == "back":
                # Go back to route editing without adding waypoint
                return await self.async_step_waypoint_list()
            
            # Get waypoint
            waypoint = user_input.get("waypoint_entity") or user_input.get("waypoint", "")
            
            if not waypoint:
                errors["base"] = "missing_waypoint"
            else:
                self._temp_waypoints.append(waypoint)
                _LOGGER.info(f"Added waypoint: {waypoint}, total: {len(self._temp_waypoints)}")
                
                if action == "add_more" and len(self._temp_waypoints) < MAX_WAYPOINTS:
                    return await self.async_step_add_waypoint()
                else:
                    return await self.async_step_waypoint_list()

        # Build action options
        actions = {
            "back": "⬅️ 취소",
            "confirm": "✅ 추가",
        }
        if current_count < MAX_WAYPOINTS - 1:
            actions["add_more"] = "➕ 추가 후 경유지 더 추가"

        data_schema = vol.Schema({
            vol.Optional("waypoint_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["device_tracker", "person", "zone"],
                )
            ),
            vol.Optional("waypoint"): selector.TextSelector(
                selector.TextSelectorConfig(
                    multiline=False,
                    type=selector.TextSelectorType.TEXT,
                )
            ),
            vol.Required("action"): vol.In(actions),
        })

        return self.async_show_form(
            step_id="add_waypoint",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "count": str(current_count + 1),
                "max": str(MAX_WAYPOINTS),
            },
        )

    async def async_step_waypoint_list(self, user_input=None):
        """Show list of waypoints and allow management."""
        if user_input is not None:
            action = user_input.get("action")
            
            if action == "add_waypoint" and len(self._temp_waypoints) < MAX_WAYPOINTS:
                return await self.async_step_add_waypoint()
            elif action == "save":
                return await self._save_route()
            elif action == "back":
                # Go back to add_route to re-edit basic info
                return await self.async_step_add_route()
            elif action.startswith("delete_"):
                idx = int(action.replace("delete_", ""))
                if 0 <= idx < len(self._temp_waypoints):
                    removed = self._temp_waypoints.pop(idx)
                    _LOGGER.info(f"Removed waypoint: {removed}")
                return await self.async_step_waypoint_list()

        # Build actions
        actions = {
            "back": "⬅️ 기본 정보 수정",
            "save": "✅ 경로 저장",
        }
        
        if len(self._temp_waypoints) < MAX_WAYPOINTS:
            actions["add_waypoint"] = f"📍 경유지 추가 ({len(self._temp_waypoints)}/{MAX_WAYPOINTS})"
        
        # Show current waypoints with delete option
        for idx, wp in enumerate(self._temp_waypoints):
            actions[f"delete_{idx}"] = f"🗑️ 경유지 {idx + 1}: {wp}"

        data_schema = vol.Schema({
            vol.Required("action"): vol.In(actions),
        })

        # Build description showing current route info
        route_info = f"출발: {self._temp_route.get('start')}\n도착: {self._temp_route.get('end')}"
        if self._temp_waypoints:
            route_info += f"\n경유지: {len(self._temp_waypoints)}개"

        return self.async_show_form(
            step_id="waypoint_list",
            data_schema=data_schema,
            description_placeholders={
                "route_info": route_info,
                "waypoint_count": str(len(self._temp_waypoints)),
                "max_waypoints": str(MAX_WAYPOINTS),
            },
        )

    async def _save_route(self):
        """Save the route with all waypoints."""
        # Generate unique route_id
        existing_ids = [int(rid.split('_')[1]) for rid in self.routes.keys() if rid.startswith('route_')]
        new_id = max(existing_ids) + 1 if existing_ids else 1
        route_id = f"route_{new_id}"
        
        route_data = {
            "start": self._temp_route.get("start"),
            "end": self._temp_route.get("end"),
            "priority": self._temp_route.get("priority", "traoptimal"),
            "name": self._temp_route.get("name"),
        }
        
        # Store waypoints
        if self._temp_waypoints:
            route_data["waypoints"] = list(self._temp_waypoints)
        
        self.routes[route_id] = route_data
        _LOGGER.info(f"Route saved: {route_id} -> {route_data}")
        
        # Clear temp storage
        self._temp_route = {}
        self._temp_waypoints = []
        
        return await self.async_step_route_list()
