"""Config flow for Kakao Navi integration."""
import logging
import asyncio
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

DOMAIN = "ha-navermaps"

class NaverMapsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kakao Navi."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Validate API keys
            api_key_id = user_input.get("X-NCP-APIGW-API-KEY-ID")
            api_key = user_input.get("X-NCP-APIGW-API-KEY")
            
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

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        return await self.async_step_route_list()

    async def async_step_route_list(self, user_input=None):
        """Show list of routes."""
        if user_input is not None:
            action = user_input.get("action")
            self.scan_interval = user_input.get("scan_interval", self.scan_interval)
            
            if action == "add":
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
        route_actions = {"add": "➕ Add new route", "save": "✅ Save and finish"}
        
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
                    if route_data.get('waypoint'):
                        display_name += f" (via {route_data['waypoint']})"
                
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
        """Add a new route."""
        errors = {}

        if user_input is not None:
            action = user_input.get("action")
            
            # Handle cancel/back action
            if action == "cancel":
                return await self.async_step_route_list()
            
            # Handle add route action
            if action == "confirm":
                # Prefer entity selection over text input
                start = user_input.get("start_entity") or user_input.get("start", "")
                end = user_input.get("end_entity") or user_input.get("end", "")
                waypoint = user_input.get("waypoint_entity") or user_input.get("waypoint", "")
                route_name = user_input.get("route_name", "").strip()
                
                if not start or not end:
                    errors["base"] = "missing_location"
                else:
                    # Generate unique route_id
                    existing_ids = [int(rid.split('_')[1]) for rid in self.routes.keys() if rid.startswith('route_')]
                    new_id = max(existing_ids) + 1 if existing_ids else 1
                    route_id = f"route_{new_id}"
                    
                    self.routes[route_id] = {
                        "start": start,
                        "end": end,
                        "waypoint": waypoint,
                        "priority": user_input.get("priority", "TIME"),
                        "name": route_name if route_name else None,
                    }
                    _LOGGER.info(f"Route added: {route_id} -> {self.routes[route_id]}")
                    _LOGGER.debug(f"Total routes now: {list(self.routes.keys())}")
                    return await self.async_step_route_list()

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
            vol.Optional("priority", default="traoptimal"): vol.In({
                "traoptimal": "Optimal (Recommended)",
                "trafast": "Fastest Route",
                "tracomfort": "Comfortable Route",
                "traavoidtoll": "Avoid Toll Roads",
                "traavoidcaronly": "Avoid Car-Only Roads",
            }),
            vol.Required("action"): vol.In({
                "cancel": "⬅️ Back",
                "confirm": "✅ Add Route",
            }),
        })

        return self.async_show_form(
            step_id="add_route",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "tip": "Choose an entity (device_tracker/person/zone) OR enter an address. Entity selection takes priority."
            },
        )
