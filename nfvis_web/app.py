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


@app.get("/dashboard/resources")
@login_required
def htmx_resources():
    api = _get_api()
    cpu = {}
    ram = {}

    # ── CPU allocation ──────────────────────────────────────────────────────
    try:
        _, raw = api.query("get_cpu_allocation")
        parsed = json.loads(raw)
        alloc = (
            parsed.get("resources:allocation")
            or parsed.get("cisco-resource-utilization:allocation")
            or parsed.get("allocation")
            or next(iter(parsed.values()), {})
        )
        if isinstance(alloc, dict):
            total      = int(alloc.get("total-logical-cpus",          0))
            system     = int(alloc.get("logical-cpus-used-by-system", 0))
            vnf        = int(alloc.get("logical-cpus-used-by-vnfs",   0))
            dedicated  = int(alloc.get("logical-cpus-used-dedicated", 0))
            sharable   = int(alloc.get("logical-cpus-used-sharable",  0))
            n_sockets  = int(alloc.get("total-sockets",               1))
            cores_per  = int(alloc.get("cores-per-socket", total // n_sockets if n_sockets else total))
            free       = total - system - vnf
            usable     = total - system
            pct        = round(vnf / usable * 100) if usable else 0
            # Build one row per socket (data is aggregated — divide evenly)
            sockets = [
                {
                    "socket": i,
                    "total":  total  // n_sockets,
                    "system": system // n_sockets,
                    "vnf":    vnf    // n_sockets,
                    "free":   free   // n_sockets,
                }
                for i in range(n_sockets)
            ]
            cpu = {
                "sockets": sockets, "n_sockets": n_sockets,
                "cores_per_socket": cores_per,
                "total": total, "system": system,
                "vnf": vnf, "vnf_dedicated": dedicated, "vnf_sharable": sharable,
                "free": free, "pct": pct,
            }
    except Exception as exc:
        app.logger.warning(f"cpu-allocation error: {exc}")

    # ── RAM info ────────────────────────────────────────────────────────────
    try:
        _, raw = api.query("get_mem_info")
        parsed = json.loads(raw)
        mem = (
            parsed.get("resources:mem-info")
            or parsed.get("cisco-resource-utilization:mem-info")
            or parsed.get("mem-info")
            or next(iter(parsed.values()), {})
        )
        if isinstance(mem, dict):
            total_mb  = int(mem.get("total-memory-mb",    0))
            system_mb = int(mem.get("system-memory-mb",   0))
            hp_total  = int(mem.get("total-hugepages-mb", 0))
            hp_free   = int(mem.get("free-hugepages-mb",  0))
            # VNF memory is hugepage-backed; allocated = reserved hugepages in use
            alloc_mb  = hp_total - hp_free
            free_mb   = hp_free
            usable    = total_mb - system_mb
            pct       = round(alloc_mb / usable * 100) if usable else 0
            ram = {"total_mb": total_mb, "system_mb": system_mb,
                   "allocated_mb": alloc_mb, "free_mb": free_mb, "pct": pct}
    except Exception as exc:
        app.logger.warning(f"mem-info error: {exc}")

    return render_template("htmx/resources.html", cpu=cpu, ram=ram)


@app.get("/dashboard/settings")
@login_required
def htmx_settings():
    api = _get_api()
    try:
        code, raw = api.query("get_settings")
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


@app.delete("/dashboard/images/<name>")
@login_required
def dashboard_image_delete(name):
    api = _get_api()
    try:
        code = api.unregister_image(name)
        if code in (200, 204):
            category, message = "success", f"Image '{name}' deleted."
        else:
            category, message = "danger", f"Delete failed (HTTP {code})."
    except Exception as exc:
        category, message = "danger", str(exc)
    resp = make_response(render_template("htmx/toast.html",
                                        category=category, message=message))
    if category == "success":
        resp.headers["HX-Trigger"] = "refreshImages"
    return resp


@app.post("/dashboard/images/register")
@login_required
def dashboard_image_register():
    api = _get_api()
    name      = request.form.get("name",      "").strip()
    url       = request.form.get("url",       "").strip()
    datastore = request.form.get("datastore", "").strip()
    try:
        payload = {"image": {
            "name": name,
            "src":  url,
            "properties": {"property": {"name": "placement", "value": datastore}},
        }}
        code = api.register_image(json.dumps(payload))
        if code not in (200, 201, 204):
            return render_template("htmx/image_reg_status.html",
                                   name=name,
                                   state=f"Registration failed (HTTP {code})",
                                   terminal=True)
        state    = api.image_state(name)
        terminal = state in ("IMAGE_ACTIVE_STATE", "IMAGE_ERROR_STATE")
        resp     = make_response(render_template("htmx/image_reg_status.html",
                                                 name=name, state=state,
                                                 terminal=terminal))
        if terminal and state == "IMAGE_ACTIVE_STATE":
            resp.headers["HX-Trigger"] = "refreshImages"
        return resp
    except Exception as exc:
        return render_template("htmx/image_reg_status.html",
                               name=name, state=str(exc), terminal=True)


@app.get("/dashboard/images/status/<name>")
@login_required
def dashboard_image_status(name):
    api = _get_api()
    try:
        state = api.image_state(name)
    except Exception as exc:
        state = str(exc)
    terminal = state in ("IMAGE_ACTIVE_STATE", "IMAGE_ERROR_STATE",
                         "IMAGE_NOT_FOUND")
    resp = make_response(render_template("htmx/image_reg_status.html",
                                         name=name, state=state,
                                         terminal=terminal))
    if terminal and state == "IMAGE_ACTIVE_STATE":
        resp.headers["HX-Trigger"] = "refreshImages"
    return resp




@app.get("/dashboard/deployments")
@login_required
def htmx_deployments():
    api = _get_api()
    try:
        # Config: image, flavor, NICs
        raw_cfg = api.get_deployments(brief=False)
        deps    = json.loads(raw_cfg).get("vmlc:deployments", {}).get("deployment", [])

        # Operational: state
        _, raw_op = api.query("get_deployments_opdata")
        op_list   = (json.loads(raw_op)
                     .get("collection", {})
                     .get("vmlc:deployments", []))
        if isinstance(op_list, dict):
            op_list = [op_list]
        op_by_name = {d.get("deployment_name"): d for d in op_list}

        # Merge state into each deployment
        for dep in deps:
            op = op_by_name.get(dep.get("name"), {})
            sm = op.get("state_machine", {})
            dep["_svc_state"] = sm.get("state", "")
            vm_sm = (sm.get("vm_state_machines", {})
                       .get("vm_state_machine", [{}]))
            if isinstance(vm_sm, dict):
                vm_sm = [vm_sm]
            dep["_vm_state"] = vm_sm[0].get("state", "") if vm_sm else ""
    except Exception as exc:
        app.logger.warning(f"htmx_deployments error: {exc}")
        deps = []
    return render_template("htmx/deployments.html", deployments=deps)


@app.delete("/dashboard/deployments/<name>")
@login_required
def dashboard_deployment_delete(name):
    api = _get_api()
    try:
        code = api.undeploy_vm(name)
        if code == 204:
            resp = make_response(
                render_template("htmx/toast.html", category="success",
                                message=f"VM '{name}' undeployed."))
            resp.headers["HX-Trigger"] = "refreshDeployments, refreshResources"
            return resp
        return render_template("htmx/toast.html", category="danger",
                               message=f"Undeploy failed (HTTP {code}).")
    except Exception as exc:
        return render_template("htmx/toast.html", category="danger", message=str(exc))


@app.post("/dashboard/deployments/<name>/action/<action>")
@login_required
def dashboard_vm_action(name, action):
    api = _get_api()
    labels = {"START": "started", "STOP": "stopped", "REBOOT": "rebooted"}
    try:
        code, _ = api.vm_action(vm_name=name, action=action)
        if code in (200, 201, 204):
            category = "success"
            message  = f"VM '{name}' {labels.get(action, action.lower())}."
        else:
            category = "danger"
            message  = f"Action failed (HTTP {code})."
    except Exception as exc:
        category, message = "danger", str(exc)
    resp = make_response(render_template("htmx/toast.html",
                                         category=category, message=message))
    if category == "success":
        resp.headers["HX-Trigger"] = "refreshDeployments, vmEdited"
    return resp


@app.get("/dashboard/deployments/<name>/edit")
@login_required
def htmx_deployment_edit(name):
    api = _get_api()
    try:
        # Current deployment config
        raw = api.get_deployments(brief=False)
        deps = json.loads(raw).get("vmlc:deployments", {}).get("deployment", [])
        dep = next((d for d in deps if d["name"] == name), None)
        if dep is None:
            return "<p class='text-danger small'>Deployment not found.</p>", 404
        vg = dep.get("vm_group", [{}])[0]
        current_flavor = vg.get("flavor", "")
        current_image  = vg.get("image", "")
        ifaces = vg.get("interfaces", {}).get("interface", [])
        if isinstance(ifaces, dict):
            ifaces = [ifaces]

        # All flavors with properties
        _, raw_flavors = api.query("get_flavors_deep")
        all_flavors = (json.loads(raw_flavors)
                       .get("vmlc:flavors", {})
                       .get("flavor", []))
        if isinstance(all_flavors, dict):
            all_flavors = [all_flavors]

        def _src_image(f):
            props = f.get("properties", {}).get("property", [])
            if isinstance(props, dict):
                props = [props]
            for p in props:
                if p.get("name") == "source_image":
                    return p.get("value", "")
            return ""

        # Disk size of the current flavor (None if not found)
        current_disk = next(
            (f.get("root_disk_mb") for f in all_flavors if f.get("name") == current_flavor),
            None
        )

        # Filter: (matching source_image OR empty source_image) AND same root_disk_mb
        flavors = [
            f.get("name") for f in all_flavors
            if (_src_image(f) == current_image or _src_image(f) == "")
            and (current_disk is None or f.get("root_disk_mb") == current_disk)
        ]

        networks = api.get_network_list(brief=True)
    except Exception as exc:
        app.logger.warning(f"htmx_deployment_edit {name}: {exc}")
        return f"<p class='text-danger small'>Error: {exc}</p>", 500
    return render_template("htmx/deployment_edit.html",
                           dep_name=name,
                           current_flavor=current_flavor,
                           ifaces=ifaces,
                           flavors=flavors,
                           networks=networks)


@app.post("/dashboard/deployments/<name>/edit")
@login_required
def htmx_deployment_edit_save(name):
    api = _get_api()
    try:
        flavor     = request.form.get("flavor", "").strip() or None
        raw_nets   = request.form.getlist("network[]")
        interfaces = [
            {"nicid": i, "network": n.strip()}
            for i, n in enumerate(raw_nets)
            if n.strip()
        ]
        if flavor:
            available_flavors = api.get_flavor_list()
            if flavor not in available_flavors:
                raise ValueError(f"Flavor '{flavor}' not found on device.")
        code, _ = api.modify_vm_interfaces(name, interfaces, flavor=flavor)
        if code in (200, 201, 204):
            category, message = "success", f"VM '{name}' updated."
        else:
            category, message = "danger", f"Update failed (HTTP {code})."
    except Exception as exc:
        category, message = "danger", str(exc)
    resp = make_response(render_template("htmx/toast.html",
                                         category=category, message=message))
    if category == "success":
        resp.headers["HX-Trigger"] = "refreshDeployments, vmEdited"
    return resp


@app.get("/dashboard/deployments/new")
@login_required
def htmx_deployment_new():
    api = _get_api()
    try:
        images   = api.get_images_with_props()
        networks = api.get_network_list(brief=True)
    except Exception as exc:
        app.logger.warning(f"deployment_new error: {exc}")
        images, networks = [], []
    return render_template("htmx/deployment_new.html", images=images, networks=networks)


@app.get("/dashboard/deployments/new/dynamic")
@login_required
def htmx_deployment_new_dynamic():
    api        = _get_api()
    image_name = request.args.get("image", "").strip()

    # ── Flavors filtered by image ────────────────────────────────────────
    flavors = []
    try:
        _, raw_flavors = api.query("get_flavors_deep")
        all_flavors = (json.loads(raw_flavors)
                       .get("vmlc:flavors", {}).get("flavor", []))
        if isinstance(all_flavors, dict):
            all_flavors = [all_flavors]

        def _src_image(f):
            props = f.get("properties", {}).get("property", [])
            if isinstance(props, dict):
                props = [props]
            for p in props:
                if p.get("name") == "source_image":
                    return p.get("value", "")
            return ""

        flavors = [f.get("name") for f in all_flavors
                   if _src_image(f) == image_name or _src_image(f) == ""]
    except Exception as exc:
        app.logger.warning(f"deployment_new_dynamic flavors: {exc}")

    # ── Custom properties + datastore hint from image opdata ─────────────
    custom_props   = []
    datastore_hint = "datastore1"
    try:
        images = api.get_images_with_props()
        img = next((i for i in images if i.get("name") == image_name), None)
        if img:
            custom_props = img.get("custom_property", [])
            if isinstance(custom_props, dict):
                custom_props = [custom_props]
            for p in img.get("property", []):
                if p.get("name") == "placement":
                    vals = p.get("value", [])
                    if vals:
                        datastore_hint = vals[0]
                    break
    except Exception as exc:
        app.logger.warning(f"deployment_new_dynamic props: {exc}")

    return render_template("htmx/deployment_new_dynamic.html",
                           flavors=flavors,
                           custom_props=custom_props,
                           datastore_hint=datastore_hint)


@app.post("/dashboard/deployments")
@login_required
def dashboard_deployment_create():
    api = _get_api()
    try:
        f         = request.form
        name      = f.get("name",      "").strip()
        image     = f.get("image",     "").strip()
        flavor    = f.get("flavor",    "").strip()
        datastore = f.get("datastore", "datastore1").strip()
        networks  = [n.strip() for n in f.getlist("network[]") if n.strip()]

        if not all([name, image, flavor, datastore]):
            return render_template("htmx/toast.html", category="danger",
                                   message="Name, Image, Flavor and Datastore are required.")

        # ── Light validation 1: name uniqueness ──────────────────────────
        try:
            raw_deps = api.get_deployments(brief=True)
            existing = [d["name"] for d in
                        json.loads(raw_deps).get("vmlc:deployments", {}).get("deployment", [])]
            if name in existing:
                return render_template("htmx/toast.html", category="danger",
                                       message=f"VM '{name}' already exists.")
        except Exception:
            pass   # let the API reject it if check fails

        # ── Light validation 2: sufficient resources ─────────────────────
        try:
            _, res_raw = api.res_check(flavor)
            res = json.loads(res_raw).get("resources:vnf", {})
            if not res.get("sufficient-resources", True):
                cause = res.get("cause", "insufficient resources")
                return render_template("htmx/toast.html", category="danger",
                                       message=f"Insufficient resources: {cause}")
        except Exception:
            pass

        # ── Build vm_config_data from custom property fields ─────────────
        cp_names = f.getlist("cp_name[]")
        cp_vals  = f.getlist("cp_value[]")
        vm_config_data = [{"name": k, "value": v}
                          for k, v in zip(cp_names, cp_vals) if k]

        # ── Build deployment payload ──────────────────────────────────────
        interfaces = [{"nicid": i, "model": "virtio", "network": n}
                      for i, n in enumerate(networks)]
        vm_group = {
            "name":                name,
            "image":               image,
            "flavor":              flavor,
            "vim_vm_name":         name,
            "bootup_time":         -1,
            "recovery_wait_time":  0,
            "interfaces":          {"interface": interfaces},
            "scaling":             {"min_active": 1, "max_active": 1},
            "placement":           [{"type": "zone_host", "host": datastore}],
            "recovery_policy":     {"action_on_recovery": "REBOOT_ONLY"},
        }
        if vm_config_data:
            vm_group["config_data"] = {
                "configuration": [{
                    "dst": "bootstrap_config",
                    "variable": [{"name": d["name"], "val": [d["value"]]}
                                 for d in vm_config_data],
                }]
            }

        payload = json.dumps({"deployment": [{"name": name, "vm_group": [vm_group]}]})


        # Bypass api.deploy_vm() (has slow pre-flight) — call query directly
        code, raw_resp = api.query("deploy_vm", payload=payload)
        if code == 201:
            resp = make_response(
                render_template("htmx/toast.html", category="success",
                                message=f"VM '{name}' deployment started."))
            resp.headers["HX-Trigger"] = "refreshDeployments, refreshResources"
            return resp

        try:
            err = json.loads(raw_resp)["errors"]["error"][0]["error-message"]
        except Exception:
            err = f"HTTP {code}"
        return render_template("htmx/toast.html", category="danger",
                               message=f"Deploy failed: {err}")

    except Exception as exc:
        app.logger.warning(f"dashboard_deployment_create error: {exc}")
        return render_template("htmx/toast.html", category="danger", message=str(exc))


@app.get("/dashboard/deployments/<name>/console")
@login_required
def dashboard_vm_console(name):
    api = _get_api()
    try:
        code, result = api.get_console(deployment=name, vm=name)
        if code in (200, 201) and result.startswith("http"):
            resp = make_response("", 204)
            resp.headers["HX-Trigger"] = json.dumps({"openConsole": {"url": result}})
            return resp
        else:
            return render_template("htmx/toast.html",
                                   category="danger",
                                   message=f"Console unavailable (HTTP {code}).")
    except Exception as exc:
        return render_template("htmx/toast.html", category="danger", message=str(exc))


def _get_bridges(api) -> list:
    try:
        return api.get_bridge_list()
    except Exception:
        return ["lan-br", "wan-br"]   # fallback so form stays usable


def _parse_vlans(raw: str) -> list:
    """'10, 20, 30' → [10, 20, 30]"""
    result = []
    for v in raw.replace(";", ",").split(","):
        v = v.strip()
        if v.isdigit():
            result.append(int(v))
    return result


@app.get("/dashboard/networks/new")
@login_required
def htmx_network_new():
    api = _get_api()
    return render_template("htmx/network_form.html",
                           bridges=_get_bridges(api),
                           is_edit=False, net={})


@app.get("/dashboard/networks/<name>/edit")
@login_required
def htmx_network_edit(name):
    api = _get_api()
    try:
        _, raw = api.query("get_networks")
        all_nets = (json.loads(raw)
                    .get("network:networks", {}).get("network", []))
        if isinstance(all_nets, dict):
            all_nets = [all_nets]
        net = next((n for n in all_nets if n.get("name") == name), {})
    except Exception as exc:
        app.logger.warning(f"network_edit fetch {name}: {exc}")
        net = {"name": name}
    return render_template("htmx/network_form.html",
                           bridges=_get_bridges(api),
                           is_edit=True, net=net)


@app.post("/dashboard/networks")
@login_required
def dashboard_network_create():
    api = _get_api()
    try:
        f           = request.form
        name        = f.get("name", "").strip()
        mode        = f.get("mode", "access")
        vlan_raw    = f.get("vlans", "").strip()
        native_vlan = f.get("native_vlan", "1").strip() or "1"
        bridge      = f.get("bridge", "lan-br").strip()

        if not name or not vlan_raw:
            return render_template("htmx/toast.html", category="danger",
                                   message="Name and VLAN(s) are required.")
        vlans = _parse_vlans(vlan_raw)
        if not vlans:
            return render_template("htmx/toast.html", category="danger",
                                   message="Invalid VLAN value.")

        net = Network(name=name, vlan=vlans, trunk=(mode == "trunk"),
                      native_vlan=int(native_vlan), bridge=bridge, sriov=False)
        code, _ = api.add_network(net.get_config())
        if code in (200, 201):
            resp = make_response(render_template("htmx/toast.html", category="success",
                                                 message=f"Network '{name}' created."))
            resp.headers["HX-Trigger"] = "refreshNetworks"
            return resp
        return render_template("htmx/toast.html", category="danger",
                               message=f"Create failed (HTTP {code}).")
    except Exception as exc:
        return render_template("htmx/toast.html", category="danger", message=str(exc))


@app.put("/dashboard/networks/<name>")
@login_required
def dashboard_network_update(name):
    api = _get_api()
    try:
        f           = request.form
        mode        = f.get("mode", "access")
        vlan_raw    = f.get("vlans", "").strip()
        native_vlan = f.get("native_vlan", "1").strip() or "1"
        bridge      = f.get("bridge", "lan-br").strip()

        vlans = _parse_vlans(vlan_raw)
        if not vlans:
            return render_template("htmx/toast.html", category="danger",
                                   message="Invalid VLAN value.")

        net = Network(name=name, vlan=vlans, trunk=(mode == "trunk"),
                      native_vlan=int(native_vlan), bridge=bridge, sriov=False)
        # PUT expects singular network object
        net_dict = json.loads(net.get_config())["network"][0]
        code, _ = api.modify_network(name, json.dumps({"network": net_dict}))
        if code in (200, 201, 204):
            resp = make_response(render_template("htmx/toast.html", category="success",
                                                 message=f"Network '{name}' updated."))
            resp.headers["HX-Trigger"] = "refreshNetworks"
            return resp
        return render_template("htmx/toast.html", category="danger",
                               message=f"Update failed (HTTP {code}).")
    except Exception as exc:
        return render_template("htmx/toast.html", category="danger", message=str(exc))


@app.delete("/dashboard/networks/<name>")
@login_required
def dashboard_network_delete(name):
    api = _get_api()
    try:
        code = api.del_network(name)
        if code == 204:
            resp = make_response(render_template("htmx/toast.html", category="success",
                                                 message=f"Network '{name}' deleted."))
            resp.headers["HX-Trigger"] = "refreshNetworks"
            return resp
        return render_template("htmx/toast.html", category="danger",
                               message=f"Delete failed (HTTP {code}).")
    except Exception as exc:
        return render_template("htmx/toast.html", category="danger", message=str(exc))


@app.get("/dashboard/networks")
@login_required
def htmx_networks():
    api = _get_api()
    try:
        code, raw = api.query("get_networks_operational")
        parsed = json.loads(raw)
        all_nets = (
            parsed.get("network:networks", {}).get("network", [])
            or parsed.get("networks", {}).get("network", [])
            or next(iter(parsed.values()), {}).get("network", [])
        )
        networks = [n for n in all_nets if not n.get("sriov")]
    except Exception as exc:
        app.logger.warning(f"get_networks_operational error: {exc}")
        networks = []
    return render_template("htmx/networks.html", networks=networks)


@app.get("/dashboard/sriov")
@login_required
def htmx_sriov():
    api = _get_api()
    try:
        code, raw = api.query("get_networks_operational")
        parsed = json.loads(raw)
        all_nets = (
            parsed.get("network:networks", {}).get("network", [])
            or parsed.get("networks", {}).get("network", [])
            or next(iter(parsed.values()), {}).get("network", [])
        )
        sriov = [n for n in all_nets if n.get("sriov")]
    except Exception:
        sriov = []
    return render_template("htmx/sriov_networks.html", networks=sriov)


@app.get("/dashboard/flavors/new")
@login_required
def htmx_flavor_new():
    api = _get_api()
    try:
        images = api.get_image_list()
    except Exception:
        images = []
    return render_template("htmx/flavor_new.html", images=images)


@app.post("/dashboard/flavors")
@login_required
def dashboard_flavor_create():
    api = _get_api()
    name         = request.form.get("name",         "").strip()
    vcpus        = request.form.get("vcpus",        "").strip()
    memory_mb    = request.form.get("memory_mb",    "").strip()
    root_disk_gb = request.form.get("root_disk_gb", "").strip()
    source_image = request.form.get("source_image", "").strip()
    description  = request.form.get("description",  "").strip()
    try:
        if not name or not vcpus or not memory_mb:
            raise ValueError("Name, vCPU and RAM are required.")
        code, _ = api.create_flavor(
            name=name,
            vcpus=int(vcpus),
            memory_mb=int(memory_mb),
            root_disk_mb=int(root_disk_gb) * 1024 if root_disk_gb else 0,
            source_image=source_image,
            description=description,
        )
        if code in (200, 201, 204):
            category, message = "success", f"Flavor '{name}' created."
        else:
            category, message = "danger", f"Create failed (HTTP {code})."
    except Exception as exc:
        category, message = "danger", str(exc)
    resp = make_response(render_template("htmx/toast.html",
                                         category=category, message=message))
    if category == "success":
        resp.headers["HX-Trigger"] = "refreshFlavors"
    return resp


@app.delete("/dashboard/flavors/<name>")
@login_required
def dashboard_flavor_delete(name):
    api = _get_api()
    try:
        code = api.delete_flavor(name)
        if code in (200, 204):
            category, message = "success", f"Flavor '{name}' deleted."
        else:
            category, message = "danger", f"Delete failed (HTTP {code})."
    except Exception as exc:
        category, message = "danger", str(exc)
    resp = make_response(render_template("htmx/toast.html",
                                         category=category, message=message))
    if category == "success":
        resp.headers["HX-Trigger"] = "refreshFlavors"
    return resp


@app.get("/dashboard/flavors")
@login_required
def htmx_flavors():
    api = _get_api()
    try:
        _, raw = api.query("get_flavors_deep")
        flavors = (json.loads(raw)
                   .get("vmlc:flavors", {})
                   .get("flavor", []))
        if isinstance(flavors, dict):
            flavors = [flavors]
    except Exception as exc:
        app.logger.warning(f"htmx_flavors error: {exc}")
        flavors = []
    return render_template("htmx/flavors.html", flavors=flavors)


@app.get("/dashboard/interfaces")
@login_required
def htmx_interfaces():
    api = _get_api()
    try:
        code, raw = api.query("get_ports")
        parsed = json.loads(raw)
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
        # Config: mode, VLANs, description
        _, raw_cfg = api.query("showPortChannel")
        cfg_col = json.loads(raw_cfg).get("collection", {})
        cfg_list = (
            cfg_col.get("switch:port-channel")
            or cfg_col.get("port-channel:port-channel")
            or cfg_col.get("port-channel")
            or []
        )
        if isinstance(cfg_list, dict):
            cfg_list = [cfg_list]
        cfg_by_port = {str(pc.get("name", "")): pc for pc in cfg_list}

        # Operational: link, speed, active members
        _, raw_op = api.query("get_portchannel_status")
        op_col = json.loads(raw_op).get("collection", {})
        op_list = (
            op_col.get("switch:port-channel")
            or op_col.get("port-channel")
            or []
        )
        if isinstance(op_list, dict):
            op_list = [op_list]

        # Merge by port number
        portchannels = []
        for op in op_list:
            port = str(op.get("Port", ""))
            cfg = cfg_by_port.get(port, {})
            swp = cfg.get("switchport", {})
            trunk = swp.get("trunk", {})
            portchannels.append({
                "name":         port,
                "description":  cfg.get("description", ""),
                "mode":         swp.get("mode", "—"),
                "native_vlan":  trunk.get("native", {}).get("vlan", "—"),
                "allowed_vlans": trunk.get("allowed", {}).get("vlan", {}).get("vlan-range", "—"),
                "access_vlan":  swp.get("access", {}).get("vlan", "—"),
                "active_ports": op.get("Active-ports", ""),
                "speed":        op.get("Speed", "—"),
                "link":         op.get("Link", "—"),
            })
    except Exception as exc:
        app.logger.warning(f"portchannels error: {exc}")
        portchannels = []
    return render_template("htmx/portchannels.html", portchannels=portchannels)


@app.get("/dashboard/switchports")
@login_required
def htmx_switchports():
    api = _get_api()
    try:
        # Config: description, shutdown, channel-group
        _, raw_cfg = api.query("get_all_swp_config")
        cfg_col = json.loads(raw_cfg).get("collection", {})
        cfg_list = (
            cfg_col.get("switch:gigabitEthernet")
            or cfg_col.get("gigabitEthernet")
            or []
        )
        if isinstance(cfg_list, dict):
            cfg_list = [cfg_list]
        cfg_by_port = {str(p.get("name", "")): p for p in cfg_list}

        # Operational: link status, mode, VLANs
        _, raw_op = api.query("get_swp_operational")
        op_col = json.loads(raw_op).get("collection", {})
        op_list = (
            op_col.get("switch:gigabitEthernet")
            or op_col.get("gigabitEthernet")
            or []
        )
        if isinstance(op_list, dict):
            op_list = [op_list]

        # Merge by port number
        switchports = []
        for op in op_list:
            port = str(op.get("Port", ""))
            cfg = cfg_by_port.get(port, {})
            cg = cfg.get("channel-group", [])
            mode = op.get("adminstrative-mode", "—")
            switchports.append({
                "name":         port,
                "description":  cfg.get("description", ""),
                "shutdown":     bool(cfg.get("shutdown")),
                "mode":         mode,
                "access_vlan":  op.get("access-mode-vlan", "—"),
                "native_vlan":  op.get("trunk-native-mode-vlan", "—"),
                "allowed_vlans": op.get("trunking-vlans", "—"),
                "port_channel": cg[0].get("cid", "") if cg else "",
                "link":         op.get("operational-mode", "—"),
            })
    except Exception as exc:
        app.logger.warning(f"switchports error: {exc}")
        switchports = []
    return render_template("htmx/switchports.html", switchports=switchports)


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
