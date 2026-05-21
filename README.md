# Cisco NFVIS API — Documentation

## Overview

Python library for managing Cisco Enterprise NFVIS (Network Functions Virtualization Infrastructure Software) appliances via REST API. Provides data models for configuring VM deployments, networks, VLANs, switchports, SNMP, TACACS, and system settings, as well as a session-based HTTP client with automatic retry.

Official API reference:
[Cisco NFVIS API Guide](https://www.cisco.com/c/en/us/td/docs/routers/nfvis/user_guide/b-api-reference-for-cisco-enterprise-nfvis/b-api-reference-for-cisco-enterprise-nfvis_chapter_01011.html)

### Project Structure

```
├── nfvis.py        API client (HTTP transport, business logic)
├── models.py       Data models (images, VMs, networks, SNMP, TACACS, ...)
├── urn_data.py     Endpoint registry (command → URL + HTTP method mapping)
```

### Dependencies

- **Python** ≥ 3.10
- **requests** (includes urllib3)

```bash
pip install requests
```

---

## Quick Start

```python
import logging
from nfvis import API
from models import Image, Network, Vm

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

api = API(url="https://10.0.0.1", username="admin", password="secret")

if api.authenticated():
    print(api.get_image_list())
    print(api.get_network_list(brief=True))
```

---

## Module Reference

### nfvis.py

Contains the `API` class and HTTP transport layer.

```python
from nfvis import API
```

### models.py

Self-contained module with no HTTP dependencies. Import models directly for configuration building, testing, or serialisation without pulling in `requests`/`urllib3`.

```python
from models import Image, Network, Vm, Switchport, TacacsServer
```

### urn_data.py

Declarative endpoint registry. Maps command names to API paths and HTTP methods. The registry is built **once at module load time**.

```python
from urn_data import get_urn_data

url, method, yang_type = get_urn_data("get_settings", "https://10.0.0.1", "")
# → ("https://10.0.0.1/api/config/system/settings?deep", "GET", "data")
```

---

## API Class

### Constructor

```python
API(url: str, username: str = "", password: str = "")
```

| Parameter  | Description                                         |
|------------|-----------------------------------------------------|
| `url`      | Base URL of the appliance (e.g. `https://10.0.0.1`) |
| `username` | API username                                        |
| `password` | API password                                        |

Creates a persistent `requests.Session` with:
- HTTP Basic auth (username/password)
- TLS verification disabled (appliances use self-signed certificates)
- Automatic retry (3 attempts, exponential backoff, on 500/502/503/504)
- 60-second timeout per request

---

### Authentication

#### `authenticated() → bool`

Performs a test call (`get_settings`) to verify credentials. Sets `api.hostname` on success.

```python
if not api.authenticated():
    raise SystemExit("Authentication failed")
print(api.hostname)
```

#### `setcreds(username: str = "", password: str = "") → None`

Updates credentials and recreates the session. Prompts interactively if arguments are omitted.

```python
api.setcreds()                           # prompts for both
api.setcreds(username="admin")           # prompts only for password
api.setcreds(username="admin", password="secret")
```

---

### Images

#### `get_image_list() → list`

Returns a list of image names registered in the system.

```python
images = api.get_image_list()
# → ["cisco-csr-16.9", "ubuntu-22.04"]
```

#### `register_image(image_config: str) → int`

Starts image registration. Returns HTTP status code.

```python
from models import Image

img = Image(name="cisco-csr-16.9", url="http://fileserver/csr.tar.gz", datastore="datastore1")
api.register_image(img.get_config())
```

#### `image_state(image_name: str) → str`

Returns the current state string of an image.

| State                  | Meaning                        |
|------------------------|--------------------------------|
| `IMAGE_ACTIVE_STATE`   | Ready for use                  |
| `IMAGE_CREATING_STATE` | Download/extraction in progress|
| `IMAGE_ERROR_STATE`    | Deployment failed              |
| `IMAGE_NOT_FOUND`      | Not registered                 |

#### `image_active(image_name: str) → bool`

Returns `True` if the image is in `IMAGE_ACTIVE_STATE`.

#### `track_image_deployment(image_config: str, interval: int = 20) → None`

Polls image state until the image becomes active, encounters an error, or is not found. Blocks the calling thread.

```python
api.track_image_deployment(img.get_config(), interval=15)
```

#### `unregister_image(image: str) → int`

Removes a registered image by name.

```python
api.unregister_image("cisco-csr-16.9")
```

---

### Flavors

#### `get_flavor_list() → list`

Returns a list of VM flavor names available on the device.

```python
flavors = api.get_flavor_list()
# → ["csr-small", "csr-medium", "isrv-small"]
```

---

### VM Deployments

#### `vm_ok_to_deploy(vm_config: str) → bool`

Pre-flight check before deployment. Verifies:
- JSON is valid and has the required structure
- No deployment with the same name already exists
- Image is in `IMAGE_ACTIVE_STATE`
- Flavor exists in the system
- All NIC networks are configured on the device
- Datastore exists (for external datastores)
- Sufficient resources are available

Returns `True` only if all checks pass. Logs individual failures.

#### `deploy_vm(vm_config: str) → int`

Runs `vm_ok_to_deploy()` first, then deploys the VM. Returns `201` on success. Raises `RuntimeError` on pre-flight failure or deployment error.

```python
from models import Vm

vm = Vm(
    name="my-router",
    image="cisco-csr-16.9",
    flavor="csr-small",
    datastore="datastore1",
    NIC0="int-mgmt-net",
    NIC1="wan-net",
    NIC2="lan-net",
)
api.deploy_vm(vm.get_config())
```

#### `undeploy_vm(vm_name: str, delay: int = 0) → int`

Removes a deployed VM. Optional `delay` (seconds) waits after removal.

```python
api.undeploy_vm("my-router", delay=10)
```

#### `get_deployments(brief: bool = True, format: str = "json") → str`

Returns raw JSON string of current deployments. If `brief=True`, retrieves only deployment names. Returns an empty deployments structure if there are no deployments.

#### `vm_action(vm_name: str, action: str, graceful: bool = False) → tuple[int, str]`

Performs a lifecycle action on a deployed VM.

| `action` value          | Effect                                          |
|-------------------------|-------------------------------------------------|
| `STOP`                  | Power off the VM                                |
| `START`                 | Power on the VM                                 |
| `REBOOT`                | Restart the VM                                  |
| `ENABLE_MONITOR`        | Enable NFVIS recovery monitoring                |
| `DISABLE_MONITOR`       | Disable NFVIS recovery monitoring               |
| `RECOVER`               | Trigger VM recovery                             |
| `DEPLOYMENT_RECOVERY`   | Trigger deployment-level recovery               |
| `SET_MONITOR_AND_RECOVER` | Enable monitoring and immediately recover     |

`graceful=True` requests a clean OS shutdown before power-off (`STOP` only).
Requires the guest to support ACPI; otherwise NFVIS forces power-off.

Raises `ValueError` for unknown action values.

```python
api.vm_action("my-router", "STOP")                    # force stop
api.vm_action("my-router", "STOP", graceful=True)     # graceful shutdown
api.vm_action("my-router", "START")
api.vm_action("my-router", "REBOOT")
```

#### `modify_vm_interfaces(vm_name: str, interfaces: list[dict]) → tuple[int, str]`

Changes NIC-to-network assignments on a deployed VM. Applies the **full** interface
list — any NIC omitted from the list is removed.

Update behaviour depends on VM state:

| VM state    | Update type  | VM reboot? |
|-------------|--------------|------------|
| `ACTIVE`    | Hot update   | No         |
| `SHUTOFF`   | Cold update  | Yes        |

```python
api.modify_vm_interfaces("my-router", [
    {"nicid": 0, "network": "int-mgmt-net"},
    {"nicid": 1, "network": "new-wan-net"},   # changed
    {"nicid": 2, "network": "lan-net"},
])
```

#### `get_vm_object_by_name(name: str) → Vm`

Fetches the live deployment configuration for *name* and returns a `Vm` instance
that reproduces it. Standard vm_group fields are mapped to constructor arguments;
any extra fields (e.g. `config_data` with bootstrap variables) are preserved.

Raises `ValueError` if no deployment with that name exists.

```python
vm = api.get_vm_object_by_name("Centos7")
print(vm.name, vm.image, vm.NIC0, vm.NIC1)
```

#### `res_check(flavor: str, low_latency: bool = False) → tuple[int, str]`

Checks whether sufficient resources are available for a given flavor.

#### `datastore_exist(datastore: str) → bool`

Returns `True` if the specified external datastore is present on the device.

---

### System Settings

#### `get_hostname() → str`

```python
hostname = api.get_hostname()
```

#### `get_ip() → str`

Returns the management IP address.

#### `set_hostname(hostname: str) → int`

```python
api.set_hostname("nfvis-lab-01")
```

#### `set_mgmt_ip(ip: str, mask: str, gateway: str) → int`

```python
api.set_mgmt_ip("10.0.0.5", "255.255.255.0", "10.0.0.1")
```

#### `set_dns_server(dns_list: list) → int`

```python
api.set_dns_server(["8.8.8.8", "8.8.4.4"])
```

#### `set_banners(banner: str = "", motd: str = "") → int`

```python
api.set_banners(banner="Authorised access only", motd="Welcome to NFVIS")
```

#### `cimc_access(enabled: bool = False) → int`

Enables or disables CIMC access through NFVIS.

#### `set_timezone(timezone: str = "UTC", location: str = "") → tuple`

Sets device timezone. Validates input against the known timezone/location table before applying.

```python
api.set_timezone("UTC")
api.set_timezone("Europe", "Moscow")
api.set_timezone("America", "New_York")
```

Returns `(None, "Invalid timezone configuration")` if validation fails.

#### `set_time(manual: bool = False, primary_server: str = "", secondary_server: str = "", time_manual: str = "") → tuple`

Configures NTP servers or sets time manually.

```python
# NTP
api.set_time(primary_server="ntp.example.com", secondary_server="ntp2.example.com")

# Manual
api.set_time(manual=True, time_manual="2025-01-15T12:00:00")
```

---

### Networks

#### `get_network_list(brief: bool = False) → list`

Returns configured networks. With `brief=True` returns a list of names; otherwise returns full network detail dicts.

```python
names = api.get_network_list(brief=True)
# → ["int-mgmt-net", "wan-net", "lan-net"]

details = api.get_network_list()
```

#### `add_network(net_config: str, form: str = "json") → tuple[int, str]`

```python
from models import Network

net = Network(name="app-net", vlan=[200], trunk=False, bridge="lan-br")
api.add_network(net.get_config())
```

#### `modify_network(network: str, net_config: str) → tuple[int, str]`

#### `del_network(network: str) → int`

---

### VLANs

#### `get_vlan_list() → list`

Returns a list of VLAN IDs configured on the internal switch.

#### `add_vlan(vlan_config: str) → int`

```python
from models import Vlan

api.add_vlan(Vlan(200).get_config())
```

#### `del_vlan(vlan: int) → int`

```python
api.del_vlan(200)
```

---

### Switchports

#### `get_swp_config(interface: str) → tuple[int, dict]`

Returns switchport configuration for a gigabit interface.

```python
code, config = api.get_swp_config("GigabitEthernet1")
```

#### `swp_config_put(config: str) → int`

Applies full switchport configuration via PUT.

```python
from models import Switchport

swp = Switchport(
    name="GigabitEthernet1",
    description="Uplink",
    mode="trunk",
    native_vlan=1,
    allowed_vlans="100-200",
)
api.swp_config_put(swp.get_config())
```

#### `swp_config_patch(config: str) → int`

Partially updates switchport configuration via PATCH.

#### `swp_shut(interface: str) → int`

Administratively shuts down a switchport.

#### `clear_swp_vlan_list(interface: str) → int`

Removes all allowed VLANs from a trunk port.

---

### TACACS

#### `get_tacacs() → tuple[int, str]`

Returns raw TACACS server configuration.

#### `reconfigure_tacacs(new_tacacs_config: str) → None`

Deletes all existing TACACS servers and applies new configuration.

```python
from models import TacacsServer, build_tacacs_config

s1 = TacacsServer(ip="10.0.0.100", shared_secret="key1", admin_priv="15")
s2 = TacacsServer(ip="10.0.0.101", shared_secret="key2", admin_priv="15")

api.reconfigure_tacacs(build_tacacs_config(s1.get_config(), s2.get_config()))
```

---

### SNMP

#### `set_snmp_sysname(name: str) → tuple[int, str]`

```python
api.set_snmp_sysname("nfvis-lab-01")
```

#### `set_snmp_traps(payload: str) → tuple[int, str]`

---

### Syslog

#### `syslog_host(hostname: str, port: int = 514) → tuple[int, str]`

```python
api.syslog_host("syslog.example.com", port=514)
```

#### `delete_syslog_host(hostname: str) → tuple[int, str]`

```python
api.delete_syslog_host("syslog.example.com")
```

---

### Console

#### `get_console(deployment: str, vm: str, openurl: bool = False) → tuple[int, str]`

Starts a VNC console session for a deployed VM.

```python
api.get_console(deployment="my-router", vm="my-router")
```

---

### Low-level Methods

#### `query(command: str, argument: str = "", payload: str = "", form: str = "json") → tuple[int, str]`

Executes any registered command directly. All commands from `urn_data.py` are available.

```python
code, result = api.query("get_settings")
code, result = api.query("get_image_status", argument="cisco-csr-16.9")
code, result = api.query("add_network", payload=net.get_config())
```

---

## Data Models

All models provide a `get_config() → str` method that returns JSON. Use `build_*` helpers to compose multi-object payloads.

### Image

```python
Image(
    name: str = None,
    url: str = None,            # source URL for download
    datastore: str = None,      # placement datastore
    image_type: str = "vm",     # "vm" | "upgrade"
)
```

```python
img = Image(name="csr", url="http://server/csr.tar.gz", datastore="datastore1")
img.get_config()
# → {"image": {"name": "csr", "src": "http://...", "properties": {...}}}
```

For system upgrade images use `image_type="upgrade"`:

```python
upgrade = Image(name="nfvis-3.12", image_type="upgrade")
```

---

### Network

```python
Network(
    name: str = None,
    vlan: list = None,
    vlan_range: list = None,    # e.g. [["100-200"], ["300-400"]]
    trunk: bool = False,
    bridge: str = "lan-br",
    sriov: bool = False,
    native_vlan: int = 1,
)
```

Access port:

```python
net = Network(name="app-net", vlan=[100])
```

Trunk port with specific VLANs:

```python
net = Network(name="trunk-net", vlan=[10, 20, 30], trunk=True, native_vlan=1)
```

Trunk port with VLAN ranges:

```python
net = Network(name="trunk-net", vlan_range=["100-200", "300-400"], trunk=True)
```

---

### Switchport

```python
Switchport(
    name: str = None,
    description: str = None,
    mode: str = "access",           # "access" | "trunk"
    vlan: int = 666,                # access VLAN (mode=access)
    native_vlan: int = 666,         # native VLAN (mode=trunk)
    allowed_vlans: str = "666",     # e.g. "100-200" (mode=trunk)
    shutdown: bool = False,
    interface_type: str = "gigabitEthernet",
    channel_group: int = None,
    channel_mode: str = "on",
)
```

```python
# Access
swp = Switchport(name="GigabitEthernet2", mode="access", vlan=100)

# Trunk
swp = Switchport(
    name="GigabitEthernet3",
    mode="trunk",
    native_vlan=1,
    allowed_vlans="100-200",
    channel_group=1,
)
```

---

### Vlan

```python
Vlan(vlan_id: int = 1)

Vlan(200).get_config()
# → {"vlan": {"vlan-id": 200}}
```

---

### SystemConfig

```python
SystemConfig(
    hostname: str = "",
    ip: str = "",
    mask: str = "",
    default_gateway: str = "",
    dns: list = None,
    cimc_access: str = "disable",   # "enable" | "disable"
)
```

---

### Vm

Keyword arguments starting with `NIC` are mapped to VM network interfaces. The key must end with a digit indicating the NIC index.

```python
Vm(
    name: str = "",
    image: str,         # required kwarg
    flavor: str,        # required kwarg
    datastore: str,     # required kwarg
    NIC0: str = "",     # network name for NIC 0
    NIC1: str = "",     # network name for NIC 1
    # ...
    config_data: str = "",  # optional JSON with extra vm_group fields
)
```

```python
vm = Vm(
    name="my-router",
    image="cisco-csr-16.9",
    flavor="csr-small",
    datastore="datastore1",
    NIC0="int-mgmt-net",
    NIC1="wan-net",
    NIC2="lan-net",
)
api.deploy_vm(vm.get_config())
```

Extra fields via `config_data`:

```python
extra = json.dumps({"bootup_time": 600, "recovery_wait_time": 30})
vm = Vm(name="my-router", ..., config_data=extra)
```

---

### SnmpGroup

```python
SnmpGroup(
    name: str = "",
    context: str = "",
    version: str = "",
    read: str = "",
    write: str = "",
    notify: str = "",
    security: str = "",     # "noAuthNoPriv" | "authNoPriv" | "authPriv"
)
```

---

### SnmpUser

```python
SnmpUser(
    name: str = "",
    version: int = 3,       # 2 | 3
    group: str = "",
    auth_proto: str = "sha",
    priv_proto: str = "aes",
    passphrase: str = "",
)
```

```python
user = SnmpUser(name="monitor", version=3, group="ReadOnly", passphrase="s3cret")
api.query("set_snmp_user", payload=user.get_config())
```

---

### SnmpHost

```python
SnmpHost(
    hostname: str = "",
    version: int = 3,
    port: int = 162,
    security_level: str = "noAuthNoPriv",
    host_ip_address: str = "",
    username: str = "",
)

host = SnmpHost(hostname="trap-mgr", host_ip_address="10.0.0.200", version=3, username="monitor")
print(host.get_config())          # JSON string
print(host.get_config(jsn=False)) # dict
```

Use `build_snmp_host_config()` to compose multiple hosts into a single payload:

```python
from models import build_snmp_host_config

payload = build_snmp_host_config(host1, host2)
api.query("set_snmp_host", payload=payload)
```

---

### TacacsServer

Returns a `dict` from `get_config()` (not JSON), intended for use with `build_tacacs_config()`.

```python
TacacsServer(
    ip: str = "",
    secret_key_id: str = "0",
    shared_secret: str = "",
    admin_priv: str = "15",
    oper_priv: str = "11",
)
```

```python
from models import TacacsServer, build_tacacs_config

s1 = TacacsServer(ip="10.0.0.100", shared_secret="key1")
s2 = TacacsServer(ip="10.0.0.101", shared_secret="key2")

payload = build_tacacs_config(s1.get_config(), s2.get_config())
api.reconfigure_tacacs(payload)
```

---

## Utilities

### `is_valid_ip(ip: str) → bool`

```python
from models import is_valid_ip
is_valid_ip("10.0.0.1")   # True
is_valid_ip("999.0.0.1")  # False
```

### `is_valid_json(data: str) → bool`

```python
from models import is_valid_json
is_valid_json('{"key": "value"}')  # True
is_valid_json("not json")          # False
```

### `check_timezone_settings(timezone: str, location: str) → bool`

Validates timezone and location against the built-in table. Prints available options on invalid input.

```python
from models import check_timezone_settings
check_timezone_settings("Europe", "Moscow")  # True
check_timezone_settings("UTC", "")           # True
check_timezone_settings("Mars", "Olympus")   # False + prints available timezones
```

### `build_tacacs_config(*servers: dict) → str`

Wraps one or more TACACS server config dicts into the API payload format.

### `build_snmp_host_config(*hosts: SnmpHost) → str`

Wraps one or more `SnmpHost` instances into the API payload format.

---

## Endpoint Registry (urn_data.py)

All API endpoints are declared in `_ENDPOINTS`. Each entry is an immutable `_Endpoint` dataclass.

### _Endpoint Fields

| Field             | Type   | Description                                                   |
|-------------------|--------|---------------------------------------------------------------|
| `path`            | `str`  | URL path after `/api/`                                        |
| `method`          | `Method` | HTTP method enum (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`)  |
| `yang_type`       | `str`  | YANG content type: `"data"` or `"collection"`                 |
| `append_argument` | `bool` | Whether the `argument` is appended to the path (default `True`) |
| `suffix`          | `str`  | Fixed string appended after the argument (e.g. `"/switchport"`) |

### Adding New Endpoints

```python
# In urn_data.py, add to _ENDPOINTS:
"my_command": _Endpoint("config/my/resource", Method.POST, "data"),

# With no argument appended:
"my_fixed":   _Endpoint("config/my/resource?deep", Method.GET, "data", append_argument=False),

# With suffix after argument:
"my_sub":     _Endpoint("running/switch/interface/gigabitEthernet", Method.GET, "data", suffix="/detail"),
```

### Selected Registered Commands

| Command                | Method   | Notes                                         |
|------------------------|----------|-----------------------------------------------|
| `get_settings`         | GET      | System settings (`?deep`)                     |
| `put_settings`         | PUT      | Update system settings                        |
| `get_image_list`       | GET      | All images (`?deep`)                          |
| `get_image_status`     | GET      | Single image state; requires `argument`       |
| `image_reg`            | POST     | Register (download) an image                  |
| `image_unreg`          | DELETE   | Remove a registered image                     |
| `get_flavors`          | GET      | Available VM flavors                          |
| `get_deployments`      | GET      | All deployments (`?deep`)                     |
| `get_deployments_brief`| GET      | Deployment names only                         |
| `deploy_vm`            | POST     | Create a VM deployment                        |
| `undeploy_vm`          | DELETE   | Remove a deployment                           |
| `resource_precheck`    | GET      | Check available resources for a flavor        |
| `get_networks`         | GET      | All networks (`?deep`)                        |
| `add_network`          | POST     |                                               |
| `del_network`          | DELETE   |                                               |
| `show_vlan`            | GET      | VLAN table (`?deep`, yang_type=`collection`)  |
| `add_vlan`             | POST     |                                               |
| `show_interface_config`| GET      | Switchport config; suffix `/switchport`       |
| `swp_config_put`       | PUT      |                                               |
| `swp_config_patch`     | PATCH    |                                               |
| `show_tacacs`          | GET      | TACACS config (`?deep`)                       |
| `configure_tacacs`     | POST     |                                               |
| `delete_tacacs_server` | DELETE   |                                               |
| `get_snmp_agent`       | GET      |                                               |
| `set_snmp_user`        | POST     |                                               |
| `set_snmp_host`        | POST     |                                               |
| `configure_syslog`     | POST     |                                               |
| `delete_syslog_server` | DELETE   |                                               |
| `set_time`             | PUT      | NTP / timezone                                |
| `set_time_manual`      | POST     | Manual time set                               |
| `vm_action`            | POST     | START / STOP / REBOOT / monitor control       |

`modify_vm_interfaces` uses two path parameters (deployment + vm_group name) and calls `_request()` directly — it is not in the registry.

For the full list see `urn_data._ENDPOINTS`.

---

## Usage Examples

### Connect and Authenticate

```python
from nfvis import API

api = API(url="https://10.0.0.1", username="admin", password="admin")

if not api.authenticated():
    raise SystemExit("Cannot connect")

print(f"Connected to {api.hostname}")
```

### Deploy a VM End-to-End

```python
from nfvis import API
from models import Image, Network, Vm

api = API(url="https://10.0.0.1", username="admin", password="admin")
api.authenticated()

# 1. Register image and wait
img = Image(name="csr", url="http://fileserver/csr.tar.gz", datastore="datastore1")
api.register_image(img.get_config())
api.track_image_deployment(img.get_config(), interval=20)

# 2. Add networks
api.add_network(Network(name="wan-net", vlan=[100]).get_config())
api.add_network(Network(name="lan-net", vlan=[200]).get_config())

# 3. Deploy VM
vm = Vm(
    name="my-router",
    image="csr",
    flavor="csr-small",
    datastore="datastore1",
    NIC0="int-mgmt-net",
    NIC1="wan-net",
    NIC2="lan-net",
)
api.deploy_vm(vm.get_config())
```

### VM Lifecycle Operations

```python
from nfvis import API

api = API(url="https://10.0.0.1", username="admin", password="admin")
api.authenticated()

# Stop — force
api.vm_action("my-router", "STOP")

# Stop — graceful OS shutdown (requires ACPI support in guest)
api.vm_action("my-router", "STOP", graceful=True)

# Start / Reboot
api.vm_action("my-router", "START")
api.vm_action("my-router", "REBOOT")

# Monitoring control
api.vm_action("my-router", "DISABLE_MONITOR")
api.vm_action("my-router", "ENABLE_MONITOR")
```

### Modify VM Network Interfaces

```python
from nfvis import API

api = API(url="https://10.0.0.1", username="admin", password="admin")
api.authenticated()

# Hot update — VM stays running, interface is remapped on the fly
api.modify_vm_interfaces("my-router", [
    {"nicid": 0, "network": "int-mgmt-net"},
    {"nicid": 1, "network": "new-wan-net"},   # was: old-wan-net
    {"nicid": 2, "network": "lan-net"},
])

# Cold update workflow — stop first, modify, start
api.vm_action("my-router", "STOP", graceful=True)
api.modify_vm_interfaces("my-router", [
    {"nicid": 0, "network": "int-mgmt-net"},
    {"nicid": 1, "network": "new-wan-net"},
])
api.vm_action("my-router", "START")

# Inspect current config, then modify
vm = api.get_vm_object_by_name("my-router")
print(vm.NIC1)   # see current network for NIC1
```

### Configure SNMP

```python
from nfvis import API
from models import SnmpGroup, SnmpUser, SnmpHost, build_snmp_host_config

api = API(url="https://10.0.0.1", username="admin", password="admin")
api.authenticated()

api.set_snmp_sysname("nfvis-lab-01")

group = SnmpGroup(name="ReadOnly", version="v3", read="all", security="authPriv")
api.query("set_snmp_groups", payload=group.get_config())

user = SnmpUser(name="monitor", group="ReadOnly", passphrase="s3cr3tP@ss")
api.query("set_snmp_user", payload=user.get_config())

host1 = SnmpHost(hostname="trap1", host_ip_address="10.0.0.200", username="monitor")
host2 = SnmpHost(hostname="trap2", host_ip_address="10.0.0.201", username="monitor")
api.query("set_snmp_host", payload=build_snmp_host_config(host1, host2))
```

### Reconfigure TACACS

```python
from nfvis import API
from models import TacacsServer, build_tacacs_config

api = API(url="https://10.0.0.1", username="admin", password="admin")
api.authenticated()

servers = build_tacacs_config(
    TacacsServer(ip="10.0.0.100", shared_secret="key1").get_config(),
    TacacsServer(ip="10.0.0.101", shared_secret="key2").get_config(),
)
api.reconfigure_tacacs(servers)
```

### Configure Switchport

```python
from nfvis import API
from models import Switchport

api = API(url="https://10.0.0.1", username="admin", password="admin")
api.authenticated()

swp = Switchport(
    name="GigabitEthernet3",
    description="Uplink to core",
    mode="trunk",
    native_vlan=1,
    allowed_vlans="100-200",
)
api.swp_config_put(swp.get_config())
```

### System Configuration

```python
api.set_hostname("nfvis-lab-01")
api.set_dns_server(["8.8.8.8", "8.8.4.4"])
api.set_timezone("Europe", "Moscow")
api.set_time(primary_server="ntp.example.com")
api.syslog_host("syslog.example.com", port=514)
api.cimc_access(enabled=False)
```

---

## HTTP Status Codes

The `return_code()` function maps status codes to human-readable messages:

| Code | Message                     |
|------|-----------------------------|
| 200  | OK                          |
| 201  | Created                     |
| 202  | Accepted                    |
| 204  | OK. No Content              |
| 400  | Bad Request                 |
| 401  | Unauthorized                |
| 403  | Forbidden                   |
| 404  | Not Found                   |
| 405  | Method Not Allowed          |
| 406  | Not Acceptable              |
| 409  | Conflict                    |

---

## Logging

The library uses Python's standard `logging` module with logger name `nfvis`.

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
```

| Level     | Usage                                                         |
|-----------|---------------------------------------------------------------|
| `DEBUG`   | Every HTTP request — method, URL, response code              |
| `INFO`    | Authentication, image state, deployment, network operations   |
| `WARNING` | Non-fatal issues (empty responses, unreachable datastores)    |
| `ERROR`   | Auth failure, resource not found, operation failed            |
| `CRITICAL`| Pre-flight check failure, invalid configuration, deploy error |
