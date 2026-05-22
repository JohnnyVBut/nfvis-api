"""NFVIS Web UI — Flask application."""

import importlib
import json
import sys
import os
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, make_response, abort,
)

# Dynamically resolve the parent package so this works regardless of
# what the enclosing directory is named (nfvis, NFVIS_API, etc.)
_here     = os.path.dirname(os.path.abspath(__file__))
_pkg_dir  = os.path.dirname(_here)       # e.g. .../NFVIS_API
_pkg_root = os.path.dirname(_pkg_dir)    # e.g. .../Python/NFVIS-API1
_pkg_name = os.path.basename(_pkg_dir)   # e.g. "NFVIS_API" or "nfvis"

sys.path.insert(0, _pkg_root)

_nfvis_mod  = importlib.import_module(f"{_pkg_name}.nfvis")
_models_mod = importlib.import_module(f"{_pkg_name}.models")

API        = _nfvis_mod.API
Image      = _models_mod.Image
Network    = _models_mod.Network
Vlan       = _models_mod.Vlan
Vm         = _models_mod.Vm
Switchport = _models_mod.Switchport

import session_store

app = Flask(__name__)
app.secret_key = os.urandom(32)   # ephemeral — regenerated on restart (local use)

_COOKIE = "nfvis_token"


# ---------------------------------------------------------------------------
#  Auth helper
# ---------------------------------------------------------------------------

def _get_api() -> API:
    """Return the API object for the current session or abort with 401."""
    token = request.cookies.get(_COOKIE)
    if not token:
        abort(401)
    api = session_store.get(token)
    if api is None:
        abort(401)
    return api


def login_required(f):
    """Decorator: redirect unauthenticated requests to /login."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.cookies.get(_COOKIE)
        if not token or session_store.get(token) is None:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
#  Auth routes
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    token = request.cookies.get(_COOKIE)
    if token and session_store.get(token):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        ip       = request.form.get("ip", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not ip or not username or not password:
            error = "All fields are required."
        else:
            try:
                url = f"https://{ip}"
                api = API(url, username, password)
                ok  = api.authenticated()
                if ok:
                    token = session_store.create(api)
                    resp  = make_response(redirect(url_for("dashboard")))
                    resp.set_cookie(_COOKIE, token, httponly=True, samesite="Lax")
                    return resp
                else:
                    error = "Authentication failed. Check credentials."
            except Exception as exc:
                error = f"Cannot connect to {ip}: {exc}"

    return render_template("login.html", error=error)


@app.get("/logout")
def logout():
    token = request.cookies.get(_COOKIE)
    if token:
        session_store.delete(token)
    resp = make_response(redirect(url_for("login")))
    resp.delete_cookie(_COOKIE)
    return resp


# ---------------------------------------------------------------------------
#  Dashboard
# ---------------------------------------------------------------------------

@app.get("/dashboard")
@login_required
def dashboard():
    api = _get_api()
    return render_template("dashboard.html", hostname=getattr(api, "hostname", api.url))


# --- HTMX fragments ---------------------------------------------------------

@app.get("/dashboard/platform")
@login_required
def htmx_platform():
    api = _get_api()
    try:
        code, raw = api.query("get_platform_detail")
        parsed = json.loads(raw)
        container = (
            parsed.get("platform_info:platform-detail")
            or parsed.get("platform-detail:platform-detail")
            or parsed.get("platform-detail")
            or next(iter(parsed.values()), {})
        )
        # Flatten nested hardware_info / software_info into a single dict
        data = {}
        for k, v in container.items():
            if isinstance(v, dict):
                data.update(v)
            else:
                data[k] = v
    except Exception as exc:
        app.logger.warning(f"platform-detail error: {exc}")
        data = {}
    return render_template("htmx/platform.html", data=data, hostname=api.hostname)


@app.get("/dashboard/diskspace")
@login_required
def htmx_diskspace():
    api = _get_api()
    try:
        code, raw = api.query("get_disk_space")
        parsed = json.loads(raw)
        container = (
            parsed.get("system:disk-space")
            or parsed.get("disk-space:disk-space")
            or parsed.get("disk-space")
            or next(iter(parsed.values()), {})
        )
        disks = container.get("disk-info", []) if isinstance(container, dict) else []
    except Exception as exc:
        app.logger.warning(f"disk-space error: {exc}")
        disks = []
    return render_template("htmx/diskspace.html", disks=disks)


@app.get("/dashboard/settings")
@login_required
def htmx_settings():
    api = _get_api()
    try:
        code, raw = api.query("get_settings")
        app.logger.debug(f"get_settings raw response: {raw[:500]}")
        parsed = json.loads(raw)
        data = (
            parsed.get("system:settings")
            or parsed.get("settings")
            or next(iter(parsed.values()), {})
        )
    except Exception as exc:
        app.logger.warning(f"get_settings error: {exc}")
        data = {}
    return render_template("htmx/settings.html", data=data)


@app.get("/dashboard/images")
@login_required
def htmx_images():
    api = _get_api()
    try:
        images = api.get_image_list()
        image_data = []
        for name in images:
            state = api.image_state(name)
            image_data.append({"name": name, "state": state})
    except Exception:
        image_data = []
    return render_template("htmx/images.html", images=image_data)


@app.get("/dashboard/deployments")
@login_required
def htmx_deployments():
    api = _get_api()
    try:
        raw  = api.get_deployments(brief=False)
        deps = json.loads(raw).get("vmlc:deployments", {}).get("deployment", [])
    except Exception:
        deps = []
    return render_template("htmx/deployments.html", deployments=deps)


@app.get("/dashboard/networks")
@login_required
def htmx_networks():
    api = _get_api()
    try:
        data = api.get_network_list(brief=False)
        app.logger.debug(f"all networks: {data}")
    except Exception:
        data = []
    return render_template("htmx/networks.html", networks=data)


@app.get("/dashboard/interfaces")
@login_required
def htmx_interfaces():
    api = _get_api()
    try:
        code, raw = api.query("get_ports")
        parsed = json.loads(raw)
        app.logger.debug(f"get_ports full response: {parsed}")
        pnics = parsed.get("pnic:pnics", {}).get("pnic", [])
    except Exception:
        pnics = []
    return render_template("htmx/interfaces.html", interfaces=pnics)


@app.get("/dashboard/vlans")
@login_required
def htmx_vlans():
    api = _get_api()
    try:
        code, raw = api.query("show_vlan")
        parsed = json.loads(raw)
        collection = parsed.get("collection", parsed)
        vlans = (
            collection.get("switch:vlan")
            or collection.get("vlan:vlan")
            or collection.get("vlan")
            or []
        )
    except Exception as exc:
        app.logger.warning(f"show_vlan error: {exc}")
        vlans = []
    return render_template("htmx/vlans.html", vlans=vlans)


@app.get("/dashboard/portchannels")
@login_required
def htmx_portchannels():
    api = _get_api()
    try:
        code, raw = api.query("showPortChannel")
        parsed = json.loads(raw)
        collection = parsed.get("collection", parsed)
        portchannels = (
            collection.get("switch:port-channel")
            or collection.get("port-channel:port-channel")
            or collection.get("port-channel")
            or []
        )
        if isinstance(portchannels, dict):
            portchannels = [portchannels]
    except Exception as exc:
        app.logger.warning(f"showPortChannel error: {exc}")
        portchannels = []
    return render_template("htmx/portchannels.html", portchannels=portchannels)


@app.get("/dashboard/switchports")
@login_required
def htmx_switchports():
    api = _get_api()
    try:
        code, raw = api.query("get_all_swp_config")
        app.logger.debug(f"get_all_swp_config raw response: {raw[:500]}")
        parsed = json.loads(raw)
        collection = parsed.get("collection", parsed)
        container = (
            collection.get("switch:gigabitEthernet")
            or collection.get("gigabitEthernet:gigabitEthernet")
            or collection.get("gigabitEthernet")
            or []
        )
        if isinstance(container, dict):
            container = [container]
    except Exception as exc:
        app.logger.warning(f"get_all_swp_config error: {exc}")
        container = []
    return render_template("htmx/switchports.html", switchports=container)


# ---------------------------------------------------------------------------
#  Configuration
# ---------------------------------------------------------------------------

@app.get("/config")
@login_required
def config():
    api = _get_api()
    try:
        images   = api.get_image_list()
        flavors  = api.get_flavor_list()
    except Exception:
        images  = []
        flavors = []
    return render_template("config.html", images=images, flavors=flavors,
                           hostname=getattr(api, "hostname", api.url))


# --- Images -----------------------------------------------------------------

@app.post("/config/image/register")
@login_required
def config_image_register():
    api  = _get_api()
    name = request.form.get("name", "").strip()
    path = request.form.get("path", "").strip()
    tag  = request.form.get("tag", "").strip() or None
    try:
        img    = Image(name=name, path=path, tag_name=tag)
        code   = api.register_image(img)
        result = ("success", f"Image '{name}' registration started (HTTP {code}).")
    except Exception as exc:
        result = ("danger", str(exc))
    return render_template("htmx/result.html", category=result[0], message=result[1])


@app.post("/config/image/unregister")
@login_required
def config_image_unregister():
    api  = _get_api()
    name = request.form.get("name", "").strip()
    try:
        code   = api.unregister_image(name)
        result = ("success", f"Image '{name}' unregistered (HTTP {code}).")
    except Exception as exc:
        result = ("danger", str(exc))
    return render_template("htmx/result.html", category=result[0], message=result[1])


# --- VMs --------------------------------------------------------------------

@app.post("/config/vm/deploy")
@login_required
def config_vm_deploy():
    api = _get_api()
    try:
        f = request.form
        # Build NIC kwargs from nic_0, nic_1, ...
        nic_kwargs = {}
        for i in range(8):
            val = f.get(f"nic_{i}", "").strip()
            if val:
                nic_kwargs[f"NIC{i}"] = val
        vm = Vm(
            name      = f.get("name", "").strip(),
            image     = f.get("image", "").strip(),
            flavor    = f.get("flavor", "").strip(),
            datastore = f.get("datastore", "").strip(),
            **nic_kwargs,
        )
        code   = api.deploy_vm(vm)
        result = ("success", f"VM '{vm.name}' deploy initiated (HTTP {code}).")
    except Exception as exc:
        result = ("danger", str(exc))
    return render_template("htmx/result.html", category=result[0], message=result[1])


@app.post("/config/vm/undeploy")
@login_required
def config_vm_undeploy():
    api  = _get_api()
    name = request.form.get("name", "").strip()
    try:
        code   = api.undeploy_vm(name)
        result = ("success", f"VM '{name}' undeployed (HTTP {code}).")
    except Exception as exc:
        result = ("danger", str(exc))
    return render_template("htmx/result.html", category=result[0], message=result[1])


@app.post("/config/vm/action")
@login_required
def config_vm_action():
    api    = _get_api()
    name   = request.form.get("name", "").strip()
    action = request.form.get("action", "").strip().upper()
    try:
        code, raw = api.vm_action(name, action)
        result    = ("success", f"{action} sent to '{name}' (HTTP {code}).")
    except Exception as exc:
        result = ("danger", str(exc))
    return render_template("htmx/result.html", category=result[0], message=result[1])


# --- Networks ---------------------------------------------------------------

@app.post("/config/network/add")
@login_required
def config_network_add():
    api  = _get_api()
    name = request.form.get("name", "").strip()
    vlan = request.form.get("vlan", "").strip()
    trunk = request.form.get("trunk", "false").lower() == "true"
    try:
        net  = Network(name=name, vlan=int(vlan) if vlan else None, trunk=trunk)
        code = api.add_network(net)
        result = ("success", f"Network '{name}' added (HTTP {code}).")
    except Exception as exc:
        result = ("danger", str(exc))
    return render_template("htmx/result.html", category=result[0], message=result[1])


@app.post("/config/network/delete")
@login_required
def config_network_delete():
    api  = _get_api()
    name = request.form.get("name", "").strip()
    try:
        code   = api.del_network(name)
        result = ("success", f"Network '{name}' deleted (HTTP {code}).")
    except Exception as exc:
        result = ("danger", str(exc))
    return render_template("htmx/result.html", category=result[0], message=result[1])


# --- VLANs ------------------------------------------------------------------

@app.post("/config/vlan/add")
@login_required
def config_vlan_add():
    api  = _get_api()
    vlan = request.form.get("vlan", "").strip()
    try:
        v    = Vlan(vlan_id=int(vlan))
        code = api.add_vlan(v)
        result = ("success", f"VLAN {vlan} added (HTTP {code}).")
    except Exception as exc:
        result = ("danger", str(exc))
    return render_template("htmx/result.html", category=result[0], message=result[1])


@app.post("/config/vlan/delete")
@login_required
def config_vlan_delete():
    api  = _get_api()
    vlan = request.form.get("vlan", "").strip()
    try:
        code   = api.del_vlan(int(vlan))
        result = ("success", f"VLAN {vlan} deleted (HTTP {code}).")
    except Exception as exc:
        result = ("danger", str(exc))
    return render_template("htmx/result.html", category=result[0], message=result[1])


# --- Switchports ------------------------------------------------------------

@app.post("/config/switchport/modify")
@login_required
def config_switchport_modify():
    api  = _get_api()
    port = request.form.get("port", "").strip()
    mode = request.form.get("mode", "").strip()
    vlan = request.form.get("vlan", "").strip()
    try:
        swp  = Switchport(port=port, mode=mode, vlan=int(vlan) if vlan else None)
        code = api.swp_config_put(swp)
        result = ("success", f"Port {port} updated (HTTP {code}).")
    except Exception as exc:
        result = ("danger", str(exc))
    return render_template("htmx/result.html", category=result[0], message=result[1])


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=5001)
