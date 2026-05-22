# NFVIS Manager — Web UI

A single-page management dashboard for Cisco Enterprise NFVIS appliances built with Flask, HTMX and Bootstrap 5. The interface provides real-time visibility and full lifecycle control of VMs, images, networks and switch infrastructure — all without writing a single line of JavaScript framework code.

---

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.10+, Flask 3.x |
| Frontend interaction | HTMX 2.0 (hypermedia, no SPA framework) |
| UI components | Bootstrap 5.3 + Bootstrap Icons 1.11 |
| Dashboard layout | Gridstack.js 10 |
| NFVIS API | Custom `nfvis.py` library (`API` class) |

---

## Architecture Overview

```
Browser
  └── base.html          # shell: navbar, modals, JS, toast container
       ├── dashboard.html # Gridstack grid of 11 card widgets
       │    └── htmx/*   # partial fragments loaded/refreshed by HTMX
       ├── config.html    # classic form-based config page
       └── login.html     # credential entry

Flask app.py
  ├── Auth routes         /login  /logout
  ├── Page routes         /dashboard  /config
  ├── HTMX partials       /dashboard/*  (GET → HTML fragments)
  └── Action routes       /dashboard/*  (POST/DELETE → toast fragment)

session_store.py          # in-memory token → API object map

nfvis.py  (parent pkg)    # REST API client (HTTP transport + business logic)
models.py (parent pkg)    # data models: Image, Vm, Network, Vlan, Switchport
urn_data.py(parent pkg)   # endpoint registry
```

### Key Design Decisions

**Hypermedia over JSON API.** Every user action returns ready-to-render HTML (HTMX fragments), not JSON. The server owns rendering logic; the browser only swaps DOM nodes.

**No client-side state.** All application state lives on the server (NFVIS device + session store). The browser holds only a session cookie.

**Partial page updates.** Cards load and refresh independently via `hx-get`. An action on one card can trigger a refresh on another via `HX-Trigger` response headers and HTMX custom events.

---

## Authentication & Session Management

### Login flow

1. User submits credentials on `/login`
2. Flask calls `api.authenticated()` against the NFVIS device
3. On success: a 64-character random token is created via `session_store.create(api)`, stored in an `HttpOnly` cookie (`nfvis_token`), and the API object is kept in server memory
4. On failure: form re-renders with an error message

### Session store (`session_store.py`)

An in-memory `dict` mapping tokens to live `API` objects. Credentials never leave the server — the cookie carries only the opaque token.

```python
token → API instance (authenticated session with NFVIS device)
```

All protected routes use the `@login_required` decorator which reads the cookie, looks up the `API` object, and redirects to `/login` if not found. HTMX partial routes use `_get_api()` which returns the `API` object or aborts with 401.

---

## Dashboard

`/dashboard` renders a **Gridstack.js** drag-and-drop grid containing 11 independent widget cards. Each card loads its content asynchronously via HTMX on page load.

### Layout & Drag-and-Drop

- **Gridstack v10** with `float: true` — cards can be placed anywhere with gaps allowed
- **Drag handle:** `.card-header` (cursor changes to move)
- **Cell height:** 70px, margin 6px
- **Layout persistence:** saved to `localStorage` under key `nfvis-dashboard-layout-v1` on every drag
- **Reset Layout button:** clears localStorage and reloads the page to restore defaults

### Card Loading Pattern

Every card body declares:
```html
hx-get="{{ url_for('htmx_*') }}"
hx-trigger="load"
hx-swap="innerHTML"
```
On page load all 11 HTMX requests fire in parallel. A spinner (`htmx/_spinner.html`) is shown until each response arrives.

### Scrollable cards with sticky headers

Card bodies scroll vertically inside the fixed grid cell. Table column headers (`thead th`) use `position: sticky; top: 0` so they remain visible while scrolling. CSS ensures the card body fills the cell height via flexbox (`flex: 1 1 0; overflow-y: auto; min-height: 0`).

---

## Dashboard Cards

### 1. Platform
**Route:** `GET /dashboard/platform`

Shows: hostname, model, software version, serial, uptime, CPU cores, total RAM. Data sourced from `get_platform` operational endpoint.

### 2. System Settings
**Route:** `GET /dashboard/settings`

Shows: management IP, mask, default gateway, DNS servers, NTP servers, timezone, hostname. Merges config and operational endpoints.

### 3. Disk Space
**Route:** `GET /dashboard/diskspace`

Shows: datastore name, total/used/free space with usage percentage bar. Sources `get_disk_space` operational endpoint.

### 4. Physical Interfaces
**Route:** `GET /dashboard/interfaces`

Shows: interface name, MAC address, IP, operational status (Up/Down badge), speed. Sources `get_interfaces` operational endpoint.

### 5. VNF Images
**Route:** `GET /dashboard/images`

The most complex read card. Features:

- **Image list** with name, state badge, trash delete button
- **Inline deployment status area** (`#deploy-status-area`) above the table for real-time registration tracking
- **Register image** via `+` button in card header → `#addImageModal`
- **OOB polling restoration:** on every images card load, `htmx/images.html` emits an out-of-band swap (`hx-swap-oob="true"`) into `#deploy-status-area` containing self-polling divs for any images in non-terminal states. This ensures polling survives page navigation and card reload.

**Image states mapped:**

| API state | Display |
|---|---|
| `IMAGE_ACTIVE_STATE` | ✅ Active (green badge) |
| `IMAGE_CREATING_STATE` | ⏳ spinner + state text |
| `IMAGE_ERROR_STATE` | ❌ Error (red badge) |
| `IMAGE_NOT_FOUND` | — Not found |

**Image actions:**
- **Delete:** `DELETE /dashboard/images/<name>` — fires confirmation modal, sends `hx-delete`, shows toast, triggers `refreshImages` to reload the card
- **Register:** `POST /dashboard/images/register` — modal form (Name, URL, Datastore — all required), modal closes immediately on submit, registration status polled every 5s via self-replacing div in `#deploy-status-area`

**Registration polling flow:**
```
POST /dashboard/images/register
  → renders image_reg_status.html into #deploy-status-area
     → if not terminal: div polls /dashboard/images/status/<name> every 5s
     → if terminal (success/error): static alert + HX-Trigger: refreshImages
```

### 6. VM Deployments
**Route:** `GET /dashboard/deployments`

The most feature-rich card. Data is merged from two NFVIS endpoints:
- **Config** endpoint: image, flavor, NIC assignments
- **Operational** endpoint (`opdata`): `_svc_state`, `_vm_state`

**Columns:** Name · Status · VM State · Image · Flavor · NICs · Actions

**Status mapping (service level):**

| `_svc_state` | Display |
|---|---|
| `SERVICE_ACTIVE_STATE` | ✅ Active |
| `SERVICE_STOPPED_STATE` | ⬜ Stopped |
| `SERVICE_ERROR_STATE` | ❌ Error |
| `SERVICE_INERT_STATE` | 🔄 spinner + Transitioning |
| any other | 🔄 spinner + raw state text |

**VM State mapping:**

| `_vm_state` | Display |
|---|---|
| `VM_INERT_STATE` | ✅ Running |
| `VM_SHUTOFF_STATE` | ⬜ Shutoff |
| `VM_ERROR_STATE` | ❌ Error |
| `VM_STARTING_STATE` | 🔄 spinner + Starting |
| `VM_SHUTTING_DOWN_STATE` / `VM_STOPPING_STATE` | 🔄 spinner + Stopping |
| `VM_REBOOTING_STATE` | 🔄 spinner + Rebooting |
| any other | 🔄 spinner + raw state text |

**Transient state logic:**
```
transient = not active and not stopped
```
During transient states: action buttons are hidden, edit button is hidden.

**Auto-polling during transitions:**
When any deployment is in a transient state (`any_transient = true`), a hidden polling div is appended after the table:
```html
<div hx-get="/dashboard/deployments"
     hx-trigger="load delay:3s"
     hx-target="#deployments-body"
     hx-swap="innerHTML">
```
This div replaces `#deployments-body` every 3 seconds. Each reload includes a new div if still transient — self-sustaining loop. Loop stops automatically when all VMs reach stable state.

**Action buttons (per row):**

| VM state | Available actions |
|---|---|
| Active | ✏️ Edit · ⏹ Stop · 🔄 Reboot |
| Stopped | ✏️ Edit · ▶️ Start |
| Transient | _(no buttons)_ |

All action buttons open a shared `#vmActionModal` with JS-populated title, body text and button color. Confirmed action fires `POST /dashboard/deployments/<name>/action/<action>`.

**VM Power actions (`POST /dashboard/deployments/<name>/action/<action>`):**
- Supported: `START`, `STOP`, `REBOOT`
- Returns: toast fragment + `HX-Trigger: refreshDeployments, vmEdited`
- `refreshDeployments` causes immediate card reload; `vmEdited` JS handler schedules additional reloads at +4s and +9s as safety net

**VM Edit (`GET + POST /dashboard/deployments/<name>/edit`):**

Edit form loaded dynamically into `#editVmModal` when pencil is clicked. The `show.bs.modal` event triggers `htmx.ajax()` to load the form via HTMX.

Form fields:
- **Flavor** — filtered dropdown: only flavors where `source_image` matches the deployment's image AND `root_disk_mb` matches the current flavor's disk size
- **NICs** — list of current network assignments, each with a network dropdown and remove button; Add NIC button appends new rows; `name="network[]"` array form fields; server assigns nicid by position (0-based)

Validation before save:
- Submitted flavor is checked against `api.get_flavor_list()` — returns error toast if not found

Save sequence (server side):
1. `PUT .../deployment/<name>/resource_group` with `{}` — resets resource reservations
2. `PUT .../deployment/<name>/vm_group/<name>/interfaces` with `{interfaces, flavor, vmexport_policy}`

After save: modal closes immediately. JS schedules `refreshDeployments` dispatches at 2s, 6s, 12s, 20s and 35s directly on `document.body` (bypasses `HX-Trigger` propagation which is unreliable after modal close). If the VM enters a transient state on any of these refreshes, the 3s transient polling takes over.

> **Note:** Hot updates (ACTIVE VM NIC change) may physically reboot the guest OS but NFVIS keeps reporting `SERVICE_ACTIVE_STATE` throughout. This is NFVIS platform behavior and is not reflected in the UI status.

**Post-action refresh architecture:**

```
VM action / edit save
  → immediate refreshDeployments  (HX-Trigger or JS)
  → vmEdited event
       → JS: refreshDeployments at +4s, +9s    [safety net]
  → if any VM transient on any refresh:
       → hidden polling div: refreshDeployments every 3s  [auto-loop]
       → loop stops when no transient VMs remain
```

### 7. Virtual Networks
**Route:** `GET /dashboard/networks`

Shows: network name, VLAN(s), trunk/access mode badge, bridge. Sources operational networks endpoint, filters out SR-IOV networks.

### 8. SR-IOV Networks
**Route:** `GET /dashboard/sriov`

Shows: network name, VLAN(s), **Mode** (Access/Trunk badge), bridge. Sources same operational endpoint as networks, shows only SR-IOV entries. Mode derived from `trunk` field.

### 9. VLANs
**Route:** `GET /dashboard/vlans`

Shows: VLAN ID list. Sources `show_vlan` config endpoint.

### 10. GigabitEthernet Ports (Switchports)
**Route:** `GET /dashboard/switchports`

Data merged from two endpoints:
- **Config** (`config/switch/interface/gigabitEthernet`): description, channel-group membership
- **Operational** (`operational/switch/interface/switchPort/gigabitEthernet`): mode, access VLAN, native VLAN, allowed VLANs, link state

**Columns:** Interface · Description · Mode · VLAN · Native VLAN · Allowed VLANs · Port-Channel · Link

Link status: Admin Down / Up (green) / Down (red).

### 11. Port-Channels
**Route:** `GET /dashboard/portchannels`

Data merged from two endpoints:
- **Config** (`config/switch/interface/port-channel`): description, mode, native VLAN, allowed VLANs
- **Operational** (`operational/switch/interface/status/port-channel`): active member ports, speed, link state

**Columns:** Interface · Description · Mode · Native VLAN · Allowed VLANs · Active Ports · Speed · Link

### 12. Flavors
**Route:** `GET /dashboard/flavors`

Shows all VM flavors with full detail. Sources `config/vm_lifecycle/flavors?deep`.

**Columns:** Name · Description · vCPU · RAM · Root Disk · Source Image

RAM and disk displayed in human-readable form (MB → GB when ≥ 1024 MB). `source_image` extracted from the nested `properties.property` list using Jinja2 `namespace` to work around loop variable scoping.

---

## Configuration Page

`/config` — classic synchronous form interface for non-dashboard operations. All actions return an `htmx/result.html` fragment with success/error styling.

### Available operations

| Category | Action | Route |
|---|---|---|
| Images | Register | `POST /config/image/register` |
| Images | Unregister | `POST /config/image/unregister` |
| VMs | Deploy | `POST /config/vm/deploy` |
| VMs | Undeploy | `POST /config/vm/undeploy` |
| VMs | Power action | `POST /config/vm/action` |
| Networks | Add | `POST /config/network/add` |
| Networks | Delete | `POST /config/network/delete` |
| VLANs | Add | `POST /config/vlan/add` |
| VLANs | Delete | `POST /config/vlan/delete` |
| Switchports | Modify | `POST /config/switchport/modify` |

---

## Shared UI Patterns

### Toast notifications

All action responses (delete, register, power action, edit) return a Bootstrap toast fragment rendered by `htmx/toast.html` and inserted into `#toast-container` via `hx-swap="beforeend"`. Toasts auto-show via the `htmx:afterSwap` event listener and auto-dismiss after 4 seconds.

Toast colors: `bg-success` (green) · `bg-danger` (red) · `bg-secondary` (grey)

### Modals

Four global Bootstrap modals in `base.html`, populated dynamically by JS:

| Modal ID | Purpose | Trigger |
|---|---|---|
| `#deleteImageModal` | Confirm image delete | `data-image-name` on trash button |
| `#addImageModal` | Register new VNF image | + button in Images card header |
| `#vmActionModal` | Confirm START/STOP/REBOOT | `data-vm-name` + `data-vm-action` on action buttons |
| `#editVmModal` | Edit VM flavor and NICs | `data-vm-name` on pencil button |

**VM Action modal pattern:**
`show.bs.modal` reads `data-vm-name` and `data-vm-action` from the triggering button, sets title/body/button class, updates `hx-post` URL on the confirm button, and calls `htmx.process()` to register the new HTMX attributes.

**Edit VM modal pattern:**
`show.bs.modal` sets the title and triggers `htmx.ajax('GET', ...)` to load the form fragment into `#editVmModalBody`. The form is loaded fresh on each open (spinner shown during load). Modal closes on submit; the form element intentionally stays in the DOM until the next open to avoid race conditions with in-flight HTMX requests.

### Cross-card refresh events

Cards that can affect other cards use HTMX custom events via `HX-Trigger` response headers:

| Event | Fired by | Consumed by |
|---|---|---|
| `refreshImages` | image delete, image register status | `#images-table-area` (`hx-trigger="refreshImages from:body"`) |
| `refreshDeployments` | VM action, VM edit, vmEdited JS handler | `#deployments-body` (`hx-trigger="refreshDeployments from:body"`) |
| `vmEdited` | VM action success, VM edit success | JS handler → schedules delayed `refreshDeployments` |

---

## HTMX Patterns Used

### Self-replacing polling div
Used for both image registration status and VM transient state monitoring:
```html
<div hx-get="<endpoint>"
     hx-trigger="load delay:3s"
     hx-target="<container>"
     hx-swap="innerHTML">
```
Each response includes a new div if the condition persists. Loop stops naturally when the condition clears.

### Out-of-band swap (OOB)
Used in `htmx/images.html` to restore polling divs in `#deploy-status-area` on every images card reload:
```html
<div id="deploy-status-area" hx-swap-oob="true">
  <!-- polling divs for in-progress images -->
</div>
```
Ensures polling survives page navigation.

### Programmatic HTMX request
Used to load the VM edit form when the modal opens without a standard `hx-get` on the button:
```javascript
htmx.ajax('GET', '/dashboard/deployments/' + name + '/edit',
          {target: '#editVmModalBody', swap: 'innerHTML'});
```

### Form array fields
NIC list in the edit form uses `name="network[]"`. Server reads with `request.form.getlist("network[]")` and assigns `nicid` by position:
```python
interfaces = [{"nicid": i, "network": n} for i, n in enumerate(raw_nets) if n.strip()]
```

---

## File Structure

```
nfvis_web/
├── app.py                          # Flask application, all routes
├── session_store.py                # In-memory token → API object store
├── requirements.txt
├── static/
│   └── style.css                   # Gridstack layout, sticky headers, drag cursor
└── templates/
    ├── base.html                   # Shell: navbar, modals, JS handlers, toast container
    ├── dashboard.html              # Gridstack grid, 11 card widgets
    ├── config.html                 # Configuration forms page
    ├── login.html                  # Login form
    └── htmx/
        ├── _spinner.html           # Loading spinner (shown while card loads)
        ├── toast.html              # Bootstrap toast fragment
        ├── result.html             # Success/error result for config page
        ├── platform.html           # Platform info card
        ├── settings.html           # System settings card
        ├── diskspace.html          # Disk space card
        ├── interfaces.html         # Physical interfaces card
        ├── images.html             # VNF images list + OOB polling restoration
        ├── image_row.html          # Single image table row
        ├── image_reg_status.html   # Image registration status (self-polling)
        ├── deployments.html        # VM deployments table + transient polling div
        ├── deployment_edit.html    # VM edit form (flavor + NIC management)
        ├── networks.html           # Virtual networks card
        ├── sriov_networks.html     # SR-IOV networks card
        ├── vlans.html              # VLANs card
        ├── switchports.html        # GigabitEthernet switchports card
        ├── portchannels.html       # Port-channels card
        └── flavors.html            # VM flavors card
```

---

## NFVIS API Endpoints Used

| Card / Feature | Endpoint | Method |
|---|---|---|
| Platform | `operational/platform-detail` | GET |
| Settings | `config/system/settings?deep` | GET |
| Disk Space | `operational/system/disk-space` | GET |
| Physical Interfaces | `operational/platform/hardware` | GET |
| VNF Images | `config/vm_lifecycle/images?deep` | GET |
| Image status | `operational/vm_lifecycle/images/image/<name>` | GET |
| Image register | `config/vm_lifecycle/images` | POST |
| Image delete | `config/vm_lifecycle/images/image/<name>` | DELETE |
| VM Deployments (config) | `config/vm_lifecycle/tenants/tenant/admin/deployments?deep` | GET |
| VM Deployments (operational) | `operational/vm_lifecycle/opdata/tenants/tenant/admin/deployments?deep` | GET |
| VM action | `operational/vm_lifecycle/tenants/tenant/admin/deployments/deployment/<name>/action` | POST |
| VM resource reset | `config/vm_lifecycle/.../deployment/<name>/resource_group` | PUT |
| VM edit (NIC + flavor) | `config/vm_lifecycle/.../deployment/<name>/vm_group/<name>/interfaces` | PUT |
| Virtual Networks | `operational/networks/network` | GET |
| Flavors | `config/vm_lifecycle/flavors?deep` | GET |
| VLANs | `config/switch/vlan?deep` | GET |
| Switchports (config) | `config/switch/interface/gigabitEthernet` | GET |
| Switchports (operational) | `operational/switch/interface/switchPort/gigabitEthernet` | GET |
| Port-channels (config) | `config/switch/interface/port-channel` | GET |
| Port-channels (operational) | `operational/switch/interface/status/port-channel` | GET |

---

## Security Notes

- Credentials are validated against the NFVIS device on every login; they are stored only in the `API` session object in server memory and never written to disk or sent to the browser
- Session tokens are 64-character cryptographically random hex strings (`secrets.token_hex(32)`)
- TLS verification is disabled for NFVIS (self-signed certificates); this is intentional for lab/appliance environments
- `app.secret_key` is ephemeral (`os.urandom(32)`) — sessions are invalidated on server restart
- All routes (except `/` and `/login`) require a valid session token via `@login_required`
