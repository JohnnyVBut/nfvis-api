"""NFVIS REST API endpoint registry.

Provides a declarative mapping of command names to API endpoints.
The public function `get_urn_data(command, url, data)` is the only
entry point consumed by nfvis.py — its signature is unchanged.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple


# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------

class Method(str, Enum):
    GET    = "GET"
    POST   = "POST"
    PUT    = "PUT"
    DELETE = "DELETE"
    PATCH  = "PATCH"


_BASE = "/api/"


# ---------------------------------------------------------------------------
#  Endpoint descriptor
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Endpoint:
    """Immutable descriptor for a single API endpoint."""
    path: str
    method: Method
    yang_type: str              # "data" or "collection"
    append_argument: bool = True
    suffix: str = ""            # appended after the argument (e.g. "/switchport")


# ---------------------------------------------------------------------------
#  Endpoint registry  (built once at module load time)
# ---------------------------------------------------------------------------

_ENDPOINTS: dict[str, _Endpoint] = {

    # --- Platform / system info -------------------------------------------
    "get_platform_detail":   _Endpoint("operational/platform-detail",                                           Method.GET,    "data"),
    "get_platform_details":  _Endpoint("operational/platform-detail",                                           Method.GET,    "data"),
    "get_settings":          _Endpoint("config/system/settings?deep",                                           Method.GET,    "data",   append_argument=False),
    "get_routes":            _Endpoint("config/system/routes",                                                  Method.GET,    "data"),
    "get_disk_space":        _Endpoint("operational/system/disk-space?deep",                                    Method.GET,    "data",   append_argument=False),
    "get_disks":             _Endpoint("operational/system/ext-disks",                                          Method.GET,    "collection"),
    "get_ports":             _Endpoint("operational/pnics?deep",                                                Method.GET,    "data",   append_argument=False),
    "get_banner":            _Endpoint("config/banner-motd",                                                    Method.GET,    "data"),
    "getUpgradeImageInfo":   _Endpoint("operational/system/upgrade/reg-info",                                   Method.GET,    "data"),
    "showPortChannel":           _Endpoint("config/switch/interface/port-channel",                              Method.GET,    "collection"),
    "get_portchannel_status":    _Endpoint("operational/switch/interface/status/port-channel",                  Method.GET,    "collection", append_argument=False),

    # --- Images -----------------------------------------------------------
    "get_image_status":      _Endpoint("operational/vm_lifecycle/opdata/images/image",                          Method.GET,    "data"),
    "get_image_list":        _Endpoint("config/vm_lifecycle/images?deep",                                       Method.GET,    "data",   append_argument=False),
    "image_reg":             _Endpoint("config/vm_lifecycle/images",                                            Method.POST,   "data"),
    "image_unreg":           _Endpoint("config/vm_lifecycle/images/image",                                      Method.DELETE, "data"),
    "reg_upgrade_pckg":      _Endpoint("config/system/upgrade",                                                 Method.POST,   "data"),

    # --- Flavors ----------------------------------------------------------
    "get_flavors":           _Endpoint("config/vm_lifecycle/flavors",                                           Method.GET,    "data"),
    "get_flavors_deep":      _Endpoint("config/vm_lifecycle/flavors?deep",                                      Method.GET,    "data",   append_argument=False),
    "get_flavor_info":       _Endpoint("config/vm_lifecycle/flavors/flavor",                                    Method.GET,    "data",   suffix="?deep"),

    # --- Deployments / VMs ------------------------------------------------
    "get_deployments":       _Endpoint("config/vm_lifecycle/tenants/tenant/admin/deployments?deep",             Method.GET,    "data",   append_argument=False),
    "get_deployments_brief": _Endpoint("config/vm_lifecycle/tenants/tenant/admin/deployments",                  Method.GET,    "data"),
    "get_deployments_opdata": _Endpoint("operational/vm_lifecycle/opdata/tenants/tenant/admin/deployments?deep", Method.GET,   "collection", append_argument=False),
    "deploy_vm":             _Endpoint("config/vm_lifecycle/tenants/tenant/admin/deployments",                  Method.POST,   "data"),
    "undeploy_vm":           _Endpoint("config/vm_lifecycle/tenants/tenant/admin/deployments/deployment",       Method.DELETE, "data"),
    "resource_precheck":     _Endpoint("operational/resources/precheck/vnf",                                    Method.GET,    "data"),
    "vm_console":            _Endpoint("operations/vncconsole/start",                                           Method.POST,   "operation"),
    "vm_action":             _Endpoint("operations/vmAction",                                                   Method.POST,   "data",   append_argument=False),
    # Note: modify_vm_interfaces uses two path params (deployment + vm_group) and is handled
    # directly in API.modify_vm_interfaces() via _request(), bypassing the registry.

    # --- Networks ---------------------------------------------------------
    "get_networks":              _Endpoint("config/networks?deep",                                              Method.GET,    "data",   append_argument=False),
    "get_networks_operational":  _Endpoint("operational/networks?deep",                                        Method.GET,    "data",   append_argument=False),
    "add_network":           _Endpoint("config/networks",                                                       Method.POST,   "data"),
    "mod_network":           _Endpoint("config/networks/network",                                               Method.PUT,    "data"),
    "del_network":           _Endpoint("config/networks/network",                                               Method.DELETE, "data"),

    # --- VLANs / switchports ----------------------------------------------
    "show_vlan":             _Endpoint("running/switch/vlan?deep",                                              Method.GET,    "collection", append_argument=False),
    "add_vlan":              _Endpoint("running/switch",                                                        Method.POST,   "data"),
    "del_vlan":              _Endpoint("running/switch/vlan",                                                   Method.DELETE, "data"),
    "show_interface_config": _Endpoint("running/switch/interface/gigabitEthernet",                              Method.GET,    "data",   suffix="/switchport"),
    "get_all_swp_config":    _Endpoint("running/switch/interface/gigabitEthernet?deep",                          Method.GET,    "collection", append_argument=False),
    "get_swp_operational":   _Endpoint("operational/switch/interface/switchPort/gigabitEthernet",                 Method.GET,    "collection", append_argument=False),
    "swp_config_put":        _Endpoint("running/switch/interface/gigabitEthernet",                              Method.PUT,    "data"),
    "swp_config_patch":      _Endpoint("running/switch/interface/gigabitEthernet",                              Method.PATCH,  "data"),
    "clear_allo_vlan":       _Endpoint("running/switch/interface/gigabitEthernet",                              Method.DELETE, "data",   suffix="/switchport/trunk/allowed/vlan/"),
    "clearVlanPortChannel":  _Endpoint("running/switch/interface/port-channel",                                 Method.DELETE, "data",   suffix="/switchport/trunk/allowed/vlan/"),
    "delete_port_channel":   _Endpoint("config/pnics/pnic",                                                     Method.DELETE, "data"),
    "unshutPortChannel":     _Endpoint("config/switch/interface/port-channel",                                  Method.DELETE, "data",   suffix="/shutdown"),
    "unshutSwitchPort":      _Endpoint("config/switch/interface/gigabitEthernet",                               Method.DELETE, "data",   suffix="/shutdown"),
    "modifyPortChannel":     _Endpoint("config/switch/interface/port-channel",                                  Method.PATCH,  "data"),

    # --- System settings --------------------------------------------------
    "put_settings":          _Endpoint("config/system/settings",                                                Method.PUT,    "data"),
    "set_banner":            _Endpoint("config/banner-motd",                                                    Method.PUT,    "data"),
    "set_time":              _Endpoint("config/system/time",                                                    Method.PUT,    "data"),
    "set_time_manual":       _Endpoint("operations/system/set-manual-time",                                     Method.POST,   "data"),
    "configure_syslog":      _Endpoint("config/system/settings/logging",                                        Method.POST,   "data"),
    "delete_syslog_server":  _Endpoint("config/system/settings/logging/host",                                   Method.DELETE, "data"),

    # --- Security / TACACS / AAA ------------------------------------------
    "show_tacacs":           _Endpoint("config/security_servers/tacacs-server?deep",                            Method.GET,    "data",   append_argument=False),
    "configure_tacacs":      _Endpoint("config/security_servers/tacacs-server",                                 Method.POST,   "data"),
    "delete_tacacs_server":  _Endpoint("config/security_servers/tacacs-server/host",                            Method.DELETE, "data"),
    "modify_tacacs":         _Endpoint("config/security_servers/tacacs-server/host",                            Method.PUT,    "data"),
    "set_aaa_method":        _Endpoint("config/security_servers/aaa",                                           Method.PATCH,  "data",   append_argument=False),

    # --- SNMP -------------------------------------------------------------
    "get_snmp_agent":        _Endpoint("config/snmp/agent",                                                     Method.GET,    "data"),
    "get_snmp_communities":  _Endpoint("config/snmp/communities",                                               Method.GET,    "data"),
    "get_snmp_groups":       _Endpoint("config/snmp/groups",                                                    Method.GET,    "data"),
    "get_snmp_users":        _Endpoint("config/snmp/users?deep",                                                Method.GET,    "data",   append_argument=False),
    "get_snmp_hosts":        _Endpoint("config/snmp/hosts?deep",                                                Method.GET,    "data",   append_argument=False),
    "get_snmp_traps":        _Endpoint("config/snmp/enable/traps?deep",                                         Method.GET,    "data",   append_argument=False),
    "set_snmp_user":         _Endpoint("config/snmp/users",                                                     Method.POST,   "data"),
    "set_snmp_host":         _Endpoint("config/snmp/hosts",                                                     Method.POST,   "data"),
    "set_snmp_communities":  _Endpoint("config/snmp/communities",                                               Method.POST,   "data"),
    "set_snmp_groups":       _Endpoint("config/snmp/groups",                                                    Method.POST,   "data"),
    "set_snmp_traps":        _Endpoint("config/snmp/enable/traps/trap-type",                                    Method.PUT,    "data",   append_argument=False),
    "set_snmp_agent_sysname": _Endpoint("config/snmp/agent/sysName",                                            Method.PUT,    "data"),
    "delete_snmp_user":      _Endpoint("config/snmp/users/user",                                                Method.DELETE, "data"),
    "delete_snmp_host":      _Endpoint("config/snmp/hosts/host",                                                Method.DELETE, "data"),
    "del_snmp_community":    _Endpoint("config/snmp/communities/community",                                     Method.DELETE, "data"),
    "del_snmp_group":        _Endpoint("config/snmp/groups/group",                                              Method.DELETE, "data"),
}


# ---------------------------------------------------------------------------
#  Public API  (signature kept for backward compatibility)
# ---------------------------------------------------------------------------

def get_urn_data(command: str, url: str, data: str = "") -> Tuple[str, str, str]:
    """
    Resolve *command* to a full URL, HTTP method, and YANG type.

    Parameters
    ----------
    command : str
        Logical command name (must exist in the endpoint registry).
    url : str
        Base URL of the NFVIS appliance, e.g. ``https://10.0.0.1``.
    data : str, optional
        Path suffix to append (e.g. ``/image-name``). Defaults to ``""``.

    Returns
    -------
    tuple[str, str, str]
        ``(full_url, http_method, yang_type)``

    Raises
    ------
    ValueError
        If *command* is not found in the registry.
    """
    endpoint = _ENDPOINTS.get(command)
    if endpoint is None:
        raise ValueError(
            f"Unknown command: '{command}'. "
            f"Available commands: {', '.join(sorted(_ENDPOINTS))}"
        )

    if endpoint.append_argument:
        full_url = f"{url}{_BASE}{endpoint.path}{data}{endpoint.suffix}"
    else:
        full_url = f"{url}{_BASE}{endpoint.path}"

    return full_url, str(endpoint.method.value), endpoint.yang_type
