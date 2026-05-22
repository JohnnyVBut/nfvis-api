"""
NFVIS REST API client.

API client with session-based HTTP transport and automatic retry.
Configuration models are defined in :mod:`models`.
"""

import getpass
import json
import logging
import time
from urllib.parse import urlparse

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth

from . import urn_data as ud
from .models import Vm, is_valid_json, check_timezone_settings, make_interface_string

urllib3.disable_warnings(InsecureRequestWarning)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Status codes
# ---------------------------------------------------------------------------

_STATUS_MESSAGES = {
    200: "OK",
    201: "Created",
    202: "Accepted",
    204: "OK. No Content",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    406: "Not Acceptable",
    409: "Conflict",
}


def return_code(code: int) -> str:
    return _STATUS_MESSAGES.get(code, f"Unknown status {code}")


# ---------------------------------------------------------------------------
#  HTTP session factory
# ---------------------------------------------------------------------------

def _create_session(
    username: str,
    password: str,
    timeout: int = 60,
    max_retries: int = 3,
    backoff_factor: float = 0.5,
) -> requests.Session:
    """
    Create a pre-configured requests.Session with:
      - Basic auth
      - TLS verification disabled (self-signed certs on appliances)
      - Automatic retry with exponential backoff
    """
    session = requests.Session()
    session.verify = False
    session.auth = HTTPBasicAuth(username, password)

    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.request_timeout = timeout  # type: ignore[attr-defined]
    return session


# ===========================================================================
#  API client
# ===========================================================================

class API:
    """
    NFVIS REST API client.

    Uses a persistent ``requests.Session`` with automatic retry
    instead of creating a new connection per request.
    """

    def __init__(self, url: str, username: str = "", password: str = ""):
        self.url = url
        self.username = username
        self.password = password
        self.hostname: str | None = None
        self._session = _create_session(username, password)

    # ------------------------------------------------------------------
    #  Low-level transport
    # ------------------------------------------------------------------

    def _request(
        self, method: str, uri: str, payload: str = "",
        yang_type: str = "data", form: str = "json",
    ) -> tuple[int, str]:
        timeout = self._session.request_timeout  # type: ignore[attr-defined]
        mime = f"application/vnd.yang.{yang_type}+{form}"
        headers = {"Content-Type": mime, "Accept": mime}

        response = self._session.request(
            method=method,
            url=uri,
            data=payload or None,
            headers=headers,
            timeout=timeout,
        )

        code = response.status_code
        content = response.text if response.content else "No content"
        logger.debug(f"{method} {uri} → {code} {return_code(code)}")
        return code, content

    def query(
        self, command: str, argument: str = "", payload: str = "", form: str = "json",
    ) -> tuple[int, str]:
        data = f"/{argument}" if argument else ""
        uri, method, yang_type = ud.get_urn_data(command, self.url, data)
        return self._request(method, uri, payload, yang_type, form)

    # ------------------------------------------------------------------
    #  Authentication
    # ------------------------------------------------------------------

    def setcreds(self, username: str = "", password: str = "") -> None:
        if username:
            self.username = username
        else:
            self.username = getpass.getuser()
            logger.info(f"Using system username: {self.username}")
        if password:
            self.password = password
        else:
            self.password = getpass.getpass(f"Password for {self.username}: ")
        self._session = _create_session(self.username, self.password)

    def authenticated(self) -> bool:
        code, settings = self.query(command="get_settings")
        if code == 200:
            self.hostname = json.loads(settings)["system:settings"]["hostname"]
            logger.info(f"User {self.username} authenticated on {self.hostname}")
            return True
        logger.error(f"Authentication failed: {code} {return_code(code)}")
        return False

    # ------------------------------------------------------------------
    #  Images
    # ------------------------------------------------------------------

    def register_image(self, image_config: str) -> int:
        name = json.loads(image_config)["image"]["name"]
        logger.info(f"Registering image {name}")
        code, _ = self.query(command="image_reg", payload=image_config)
        logger.info(f"register_image {name}: {code} {return_code(code)}")
        return code

    def image_state(self, image_name: str) -> str:
        code, response = self.query(command="get_image_status", argument=image_name)
        if code == 404:
            return "IMAGE_NOT_FOUND"
        return json.loads(response)["vmlc:image"]["state"]

    def image_active(self, image_name: str) -> bool:
        return self.image_state(image_name) == "IMAGE_ACTIVE_STATE"

    def track_image_deployment(self, image_config: str, interval: int = 20) -> None:
        cfg = json.loads(image_config)
        image_name = cfg["image"]["name"]
        image_url = cfg["image"]["src"]
        while True:
            state = self.image_state(image_name)
            if state == "IMAGE_ACTIVE_STATE":
                logger.info(f"Image {image_name} is in {state}")
                break
            if state == "IMAGE_NOT_FOUND":
                logger.error(f"{state}. Check name ({image_name}) or reachability of {image_url}")
                break
            if state == "IMAGE_ERROR_STATE":
                logger.error(f"{state}. Deployment of {image_name} failed. Check archive and CRC")
                break
            logger.info(f"Image {image_name}: {state}")
            time.sleep(interval)

    def unregister_image(self, image: str) -> int:
        code = self.query("image_unreg", argument=image)[0]
        if code == 204:
            logger.info(f"Image {image} unregistered")
        else:
            logger.error(f"Unable to unregister {image}: {code} {return_code(code)}")
        return code

    def get_image_list(self) -> list:
        code, response = self.query(command="get_image_list")
        try:
            return [i["name"] for i in json.loads(response)["vmlc:images"]["image"]]
        except (KeyError, json.JSONDecodeError):
            logger.error(f"Unable to get image list: {code} {return_code(code)}")
            return []

    # ------------------------------------------------------------------
    #  Flavors
    # ------------------------------------------------------------------

    def get_flavor_list(self) -> list:
        code, response = self.query(command="get_flavors")
        if code == 200:
            return [i["name"] for i in json.loads(response)["vmlc:flavors"]["flavor"]]
        logger.error(f"Unable to get flavor list: {code} {return_code(code)}")
        return []

    def create_flavor(
        self,
        name: str,
        vcpus: int,
        memory_mb: int,
        root_disk_mb: int = 0,
        source_image: str = "",
        description: str = "",
    ) -> tuple[int, str]:
        flavor: dict = {"name": name, "vcpus": vcpus, "memory_mb": memory_mb}
        if root_disk_mb:
            flavor["root_disk_mb"] = root_disk_mb
        if description:
            flavor["description"] = description
        if source_image:
            flavor["properties"] = {
                "property": [{"name": "source_image", "value": source_image}]
            }
        logger.info(f"Creating flavor {name} ({vcpus} vCPU, {memory_mb} MB RAM)")
        return self.query("create_flavor", payload=json.dumps({"flavor": flavor}))

    def delete_flavor(self, name: str) -> int:
        code, _ = self.query("delete_flavor", argument=name)
        if code in (200, 204):
            logger.info(f"Flavor {name} deleted")
        else:
            logger.error(f"Unable to delete flavor {name}: {code} {return_code(code)}")
        return code

    # ------------------------------------------------------------------
    #  VMs / deployments
    # ------------------------------------------------------------------

    def vm_ok_to_deploy(self, vm_config: str) -> bool:
        if not is_valid_json(vm_config):
            logger.critical("VM configuration JSON validation error")
            return False

        logger.info("VM configuration check starting")

        try:
            conf = json.loads(vm_config)["deployment"][0]
            vm_group = conf["vm_group"][0]
            vm_name = vm_group["name"]
            vm_image = vm_group["image"]
            vm_flavor = vm_group["flavor"]
            datastore = vm_group["placement"][0]["host"]
            vm_nics = vm_group["interfaces"]["interface"]
        except (KeyError, IndexError, json.JSONDecodeError):
            logger.critical("Invalid VM configuration structure")
            return False

        configured_nics = self.get_network_list(brief=True)
        configured_nics.append("int-mgmt-net")

        deployments_data = json.loads(self.get_deployments(brief=True))
        deployments_list = [d["name"] for d in deployments_data["vmlc:deployments"]["deployment"]]

        name_ok = vm_name not in deployments_list
        if not name_ok:
            logger.error(f"VM {vm_name} is already deployed")

        image_ok = self.image_state(vm_image) == "IMAGE_ACTIVE_STATE"
        if not image_ok:
            logger.error(f"Image {vm_image} is not in ACTIVE state")

        flavor_ok = vm_flavor in self.get_flavor_list()
        if not flavor_ok:
            logger.error(f"Flavor {vm_flavor} does not exist")

        nics_ok = True
        for nic in vm_nics:
            if nic["network"] in configured_nics:
                logger.info(f"Network {nic['network']} for NIC{nic['nicid']} found")
            else:
                logger.error(f"Network {nic['network']} for NIC{nic['nicid']} not found")
                nics_ok = False

        ext_datastore_list = ["datastore2", "datastore3"]
        datastore_ok = True
        if datastore in ext_datastore_list:
            datastore_ok = self.datastore_exist(datastore)
            if not datastore_ok:
                logger.error(f"Datastore {datastore} not found")

        resource_check = json.loads(self.res_check(vm_flavor)[1])["resources:vnf"]
        sufficient_resources = resource_check["sufficient-resources"]
        cause = resource_check["cause"]

        if all([name_ok, image_ok, flavor_ok, nics_ok, datastore_ok, sufficient_resources]):
            logger.info("All VM config checks passed")
            return True

        logger.critical(
            f"Cannot deploy {vm_name} from {vm_image}. Summary:\n"
            f"  Name: {name_ok}, Image: {image_ok}, Flavor: {flavor_ok}, "
            f"NICs: {nics_ok}, Datastore: {datastore_ok}, "
            f"Resources: {sufficient_resources} ({cause})"
        )
        return False

    def deploy_vm(self, vm_config: str) -> int:
        conf = json.loads(vm_config)["deployment"][0]["vm_group"][0]
        logger.info(f"Deploying VM {conf['name']} from image {conf['image']} flavor {conf['flavor']}")

        if not self.vm_ok_to_deploy(vm_config):
            raise RuntimeError(f"VM {conf['name']} pre-flight check failed")

        code, errors = self.query(command="deploy_vm", payload=vm_config)
        if code == 201:
            logger.info(f"VM {conf['name']} deployed successfully")
            return code

        error_msg = json.loads(errors)["errors"]["error"][0]["error-message"]
        logger.critical(f"VM {conf['name']} deployment failed ({code}): {error_msg}")
        raise RuntimeError(f"deploy_vm failed with code {code}: {error_msg}")

    def undeploy_vm(self, vm_name: str, delay: int = 0) -> int:
        code, _ = self.query("undeploy_vm", vm_name)
        if code == 204:
            logger.info(f"VM {vm_name} removed successfully")
            if delay:
                time.sleep(delay)
        else:
            logger.critical(f"Unable to remove VM {vm_name}: {code} {return_code(code)}")
        return code

    # Valid values for the *action* parameter of vm_action()
    VM_ACTIONS = frozenset({
        "START", "STOP", "REBOOT",
        "ENABLE_MONITOR", "DISABLE_MONITOR",
        "RECOVER", "DEPLOYMENT_RECOVERY", "SET_MONITOR_AND_RECOVER",
    })

    def vm_action(self, vm_name: str, action: str, graceful: bool = False) -> tuple[int, str]:
        """
        Perform a lifecycle action on a deployed VM.

        Parameters
        ----------
        vm_name : str
            Name of the VM deployment (and vm_group — they are always identical in NFVIS).
        action : str
            One of: START, STOP, REBOOT, ENABLE_MONITOR, DISABLE_MONITOR,
            RECOVER, DEPLOYMENT_RECOVERY, SET_MONITOR_AND_RECOVER.
        graceful : bool
            If True, requests a graceful OS shutdown before stopping.
            Requires the guest to support ACPI.
            Only relevant when action="STOP".

        Behaviour
        ---------
        STOP on a running VM  → hot stop  (no reboot of underlying host).
        STOP on a shut-off VM → no-op.
        If the VM supports ACPI and graceful=True, the guest OS shuts down
        cleanly; otherwise NFVIS forces power-off immediately.
        """
        action = action.upper()
        if action not in self.VM_ACTIONS:
            raise ValueError(f"Unknown action {action!r}. Valid: {', '.join(sorted(self.VM_ACTIONS))}")

        payload: dict = {"vmlc:actionType": action, "vmlc:vmName": vm_name}
        if graceful and action == "STOP":
            payload["vmlc:gracefulShutdown"] = None

        logger.info(f"vm_action {action} → {vm_name}" + (" (graceful)" if graceful else ""))
        return self.query(command="vm_action", payload=json.dumps(payload))

    def modify_vm_interfaces(
        self,
        vm_name: str,
        interfaces: list[dict],
        flavor: str = None,
    ) -> tuple[int, str]:
        """
        Change NIC-to-network assignments (and optionally flavor) for a deployed VM.

        This is a **hot or cold update** depending on VM state:
        - VM is ACTIVE  → hot update, no reboot required.
        - VM is SHUTOFF → cold update, VM reboots during the operation.

        The full interface list must be supplied — omitting a NIC removes it.

        Parameters
        ----------
        vm_name : str
            Deployment name (also used as vm_group name — always identical in NFVIS).
        interfaces : list[dict]
            Each dict must have ``nicid`` (int) and ``network`` (str).
        flavor : str, optional
            New flavor name. If provided, the VM flavor is updated together
            with the interface list.

        Example
        -------
        api.modify_vm_interfaces("my-router", [
            {"nicid": 0, "network": "int-mgmt-net"},
            {"nicid": 1, "network": "new-wan-net"},
            {"nicid": 2, "network": "lan-net"},
        ])

        Notes
        -----
        The URL for this endpoint embeds the deployment name and vm_group name
        as two separate path segments.  Because they are always the same value
        in NFVIS, we use vm_name for both and call _request() directly,
        bypassing the endpoint registry which supports only one path argument.

        A preparatory PUT to the resource_group sub-resource is required before
        the interface update — this resets resource reservations so that the
        device accepts the new configuration.
        """
        base = (
            f"{self.url}/api/config/vm_lifecycle/tenants/tenant/admin"
            f"/deployments/deployment/{vm_name}"
        )

        # Step 1: reset resource group (required before interface/flavor change)
        rg_code, _ = self._request(
            "PUT", f"{base}/resource_group", "{}", yang_type="data", form="json"
        )
        if rg_code not in (200, 201, 204):
            logger.warning(f"modify_vm_interfaces: resource_group PUT returned {rg_code}")

        # Step 2: update interfaces (and optionally flavor)
        payload_dict: dict = {
            "interfaces": {"interface": interfaces},
            "vmexport_policy": {"disk_exclusion": []},
        }
        if flavor:
            payload_dict["flavor"] = flavor

        logger.info(
            f"modify_vm_interfaces {vm_name}: {len(interfaces)} NIC(s)"
            + (f", flavor={flavor}" if flavor else "")
        )
        return self._request(
            "PUT", f"{base}/vm_group/{vm_name}/interfaces",
            json.dumps(payload_dict), yang_type="data", form="json"
        )

    def get_deployments(self, brief: bool = True, format: str = "json") -> str:
        logger.info("Getting deployments")
        cmd = "get_deployments_brief" if brief else "get_deployments"
        code, content = self.query(cmd, form=format)
        logger.debug(f"get_deployments: {code} {return_code(code)}")
        if content == "No content":
            return '{"vmlc:deployments": {"deployment": []}}'
        return content

    def get_vm_object_by_name(self, name: str) -> Vm:
        """
        Fetch the live deployment configuration for *name* and return
        a :class:`models.Vm` instance that reproduces it.

        Standard vm_group fields (name, image, flavor, vim_vm_name,
        bootup_time, recovery_wait_time, interfaces, scaling, placement,
        recovery_policy) are mapped to Vm constructor arguments.
        Any extra fields present in the deployment are preserved via
        ``config_data`` so that ``vm.get_config()`` round-trips cleanly.

        Raises
        ------
        ValueError
            If no deployment named *name* exists on the device.
        """
        deployments_raw = self.get_deployments(brief=False)
        try:
            deployments = json.loads(deployments_raw)["vmlc:deployments"]["deployment"]
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to parse deployments response: {exc}") from exc

        deployment = next((d for d in deployments if d["name"] == name), None)
        if deployment is None:
            raise ValueError(f"VM deployment '{name}' not found on {self.hostname or self.url}")

        vm_group = deployment["vm_group"][0]

        # NIC interfaces → NIC0, NIC1, ... keyword arguments
        nic_kwargs = {
            f"NIC{nic['nicid']}": nic["network"]
            for nic in vm_group.get("interfaces", {}).get("interface", [])
        }

        # Fields that Vm.__init__ already handles explicitly
        _STANDARD_FIELDS = {
            "name", "image", "flavor", "vim_vm_name",
            "bootup_time", "recovery_wait_time",
            "interfaces", "scaling", "placement", "recovery_policy",
        }
        extra = {k: v for k, v in vm_group.items() if k not in _STANDARD_FIELDS}

        kwargs: dict = dict(
            name=name,
            image=vm_group["image"],
            flavor=vm_group["flavor"],
            datastore=vm_group["placement"][0]["host"],
            **nic_kwargs,
        )
        if extra:
            kwargs["config_data"] = json.dumps(extra)

        logger.info(f"Restored Vm object for deployment '{name}'")
        return Vm(**kwargs)

    def res_check(self, flavor: str, low_latency: bool = False) -> tuple[int, str]:
        config = f"TestVM,{flavor},{str(low_latency).lower()}"
        return self.query("resource_precheck", config, "", "json")

    def datastore_exist(self, datastore: str) -> bool:
        try:
            for i in json.loads(self.query("get_disks")[1])["collection"]["system:ext-disks"]:
                if int(i["name"][-1]) + 1 == int(datastore[-1]):
                    return True
            return False
        except (KeyError, ValueError, json.JSONDecodeError):
            return False

    # ------------------------------------------------------------------
    #  System settings
    # ------------------------------------------------------------------

    def get_hostname(self) -> str:
        self.hostname = json.loads(self.query("get_settings")[1])["system:settings"]["hostname"]
        return self.hostname

    def get_ip(self) -> str:
        return json.loads(self.query("get_settings")[1])["system:settings"]["mgmt"]["ip"]["address"]

    def set_hostname(self, hostname: str) -> int:
        system_config = json.loads(self.query("get_settings")[1])
        system_config["system:settings"]["hostname"] = hostname
        logger.info(f"Setting hostname to {hostname}")
        return self.query(command="put_settings", payload=json.dumps(system_config))[0]

    def set_mgmt_ip(self, ip: str = "", mask: str = "", gateway: str = "") -> int:
        system_config = json.loads(self.query("get_settings")[1])
        system_config["system:settings"]["mgmt"]["ip"] = ip
        system_config["system:settings"]["mgmt"]["netmask"] = mask
        system_config["system:settings"]["default-gw"] = gateway
        logger.info(f"Setting management IP to {ip}/{mask}, gateway {gateway}")
        return self.query(command="put_settings", payload=json.dumps(system_config))[0]

    def set_dns_server(self, dns_list: list) -> int:
        system_config = json.loads(self.query("get_settings")[1])
        system_config["system:settings"]["dns-server"] = dns_list
        logger.info(f"Setting DNS servers to {dns_list}")
        return self.query(command="put_settings", payload=json.dumps(system_config))[0]

    def set_banners(self, banner: str = "", motd: str = "") -> int:
        payload = json.dumps({"banner-motd": {"motd": motd, "banner": banner}})
        return self.query(command="set_banner", payload=payload)[0]

    def cimc_access(self, enabled: bool = False) -> int:
        system_config = json.loads(self.query("get_settings")[1])
        state = "enable" if enabled else "disable"
        system_config["system:settings"]["cimc-access"] = state
        logger.info(f"CIMC access: {state}")
        return self.query(command="put_settings", payload=json.dumps(system_config))[0]

    def set_timezone(self, timezone: str = "UTC", location: str = "") -> tuple[int, str] | tuple[None, str]:
        if not check_timezone_settings(timezone, location):
            logger.critical(f"Invalid timezone: {timezone}/{location}")
            return None, "Invalid timezone configuration"
        tz = f"{timezone}/{location}" if timezone != "UTC" else timezone
        payload = json.dumps({"time": {"timezone": tz}})
        logger.info(f"Setting timezone to {tz}")
        return self.query(command="set_time", payload=payload)

    def set_time(
        self, manual: bool = False, primary_server: str = "",
        secondary_server: str = "", time_manual: str = "",
    ) -> tuple[int, str]:
        if manual:
            payload = {"input": {"time": time_manual}}
            return self.query(command="set_time_manual", payload=json.dumps(payload))

        ntp: dict = {
            "preferred_server": primary_server,
            "preferred_server_type": "domain-name",
        }
        if secondary_server:
            ntp["backup_server"] = secondary_server
            ntp["backup_server_type"] = "domain-name"
        payload = {"time": {"ntp": ntp}}
        return self.query(command="set_time", payload=json.dumps(payload))

    # ------------------------------------------------------------------
    #  Networks
    # ------------------------------------------------------------------

    def get_net(self) -> tuple[int, str]:
        return self.query(command="get_networks")

    def get_network_list(self, brief: bool = False) -> list:
        code, result = self.query(command="get_networks")
        if code != 200:
            logger.warning(f"Unable to get network list: {code} {return_code(code)}")
            return []
        networks = json.loads(result)["network:networks"]["network"]
        if brief:
            return [n["name"] for n in networks]
        return networks

    def add_network(self, net_config: str, form: str = "json") -> tuple[int, str]:
        network = json.loads(net_config)["network"][0]["name"]
        logger.info(f"Adding network {network}")
        return self.query(command="add_network", payload=net_config, form=form)

    def modify_network(self, network: str, net_config: str) -> tuple[int, str]:
        return self.query("mod_network", network, net_config)

    def del_network(self, network: str) -> int:
        logger.info(f"Deleting network {network}")
        code, _ = self.query("del_network", str(network))
        return code

    # ------------------------------------------------------------------
    #  VLANs
    # ------------------------------------------------------------------

    def get_vlan_list(self) -> list:
        _, content = self.query(command="show_vlan")
        return [v["vlan-id"] for v in json.loads(content)["collection"]["switch:vlan"]]

    def add_vlan(self, vlan_config: str) -> int:
        vlan = json.loads(vlan_config)["vlan"]["vlan-id"]
        logger.info(f"Adding VLAN {vlan}")
        return self.query("add_vlan", payload=vlan_config)[0]

    def del_vlan(self, vlan: int) -> int:
        logger.info(f"Deleting VLAN {vlan}")
        return self.query("del_vlan", str(vlan))[0]

    # ------------------------------------------------------------------
    #  Switchports
    # ------------------------------------------------------------------

    def get_swp_config(self, interface: str) -> tuple[int, dict]:
        code, content = self.query("show_interface_config", argument=make_interface_string(interface))
        return code, json.loads(content)

    def clear_swp_vlan_list(self, interface: str) -> int:
        logger.info(f"Clearing allowed VLANs from interface {interface}")
        return self.query(command="clear_allo_vlan", argument=make_interface_string(interface))[0]

    def swp_config_patch(self, config: str) -> int:
        return self.query("swp_config_patch", "", config, "json")[0]

    def swp_config_put(self, config: str) -> int:
        config_json = json.loads(config)
        interface_type = next(iter(config_json))
        interface_number = config_json[interface_type]["name"]
        logger.info(f"Configuring interface {interface_type}{interface_number}")
        return self.query("swp_config_put", argument=make_interface_string(interface_number), payload=config)[0]

    def swp_shut(self, interface: str) -> int:
        swp = {"gigabitEthernet": {"name": interface, "shutdown": ""}}
        return self.query("swp_config_patch", payload=json.dumps(swp))[0]

    # ------------------------------------------------------------------
    #  TACACS
    # ------------------------------------------------------------------

    def get_tacacs(self) -> tuple[int, str]:
        return self.query("show_tacacs")

    def reconfigure_tacacs(self, new_tacacs_config: str) -> None:
        if not is_valid_json(new_tacacs_config):
            logger.error("Invalid TACACS configuration JSON")
            return

        code, tacacs_configured = self.get_tacacs()
        if tacacs_configured != "No content":
            for server_record in json.loads(tacacs_configured)["security:tacacs-server"]["host"]:
                server_ip = server_record["server"]
                del_code = self.query("delete_tacacs_server", argument=server_ip)[0]
                logger.info(f"Deleted TACACS server {server_ip}: {del_code} {return_code(del_code)}")

        add_code = self.query("configure_tacacs", payload=new_tacacs_config)[0]
        logger.info(f"Configured TACACS servers: {add_code} {return_code(add_code)}")

    # ------------------------------------------------------------------
    #  SNMP
    # ------------------------------------------------------------------

    def set_snmp_sysname(self, name: str) -> tuple[int, str]:
        return self.query(command="set_snmp_agent_sysname", payload=json.dumps({"sysName": name}))

    def set_snmp_traps(self, payload: str) -> tuple[int, str]:
        return self.query(command="set_snmp_traps", payload=payload)

    # ------------------------------------------------------------------
    #  Syslog
    # ------------------------------------------------------------------

    def syslog_host(self, hostname: str, port: int = 514) -> tuple[int, str]:
        config = {"host": {"host": hostname, "port": str(port), "transport": {"udp": ""}}}
        return self.query(command="configure_syslog", payload=json.dumps(config))

    def delete_syslog_host(self, hostname: str) -> tuple[int, str]:
        return self.query(command="delete_syslog_server", argument=hostname)

    # ------------------------------------------------------------------
    #  Console
    # ------------------------------------------------------------------

    def get_console(self, deployment: str, vm: str) -> tuple[int, str]:
        """
        Request a VNC console URL for a running VM.

        Returns
        -------
        tuple[int, str]
            ``(http_code, vnc_url)`` on success, where *vnc_url* is fully
            qualified (e.g. ``https://172.30.200.8:6005/vnc_auto.html``).
            On failure returns ``(http_code, raw_error_body)``.
        """
        payload = json.dumps({"input": {"deployment-name": deployment, "vm-name": vm}})
        code, content = self.query("vm_console", "", payload, "json")
        logger.debug(f"get_console raw response [{code}]: {content}")
        if code not in (200, 201):
            logger.warning(f"get_console {deployment}/{vm}: {code} {return_code(code)}")
            return code, content
        try:
            relative_url = json.loads(content)["vncconsole:output"]["vncconsole-url"]
            # relative_url is like ":6005/vnc_auto.html" — prepend https + hostname
            hostname = urlparse(self.url).hostname
            full_url = f"https://{hostname}{relative_url}"
            logger.info(f"get_console {deployment}/{vm}: {full_url}")
            return code, full_url
        except (KeyError, json.JSONDecodeError) as exc:
            logger.warning(f"get_console: failed to parse URL from response: {exc}")
            return code, f"Error parsing console URL: {exc}"
