"""NFVIS data models — configuration builders and input validators."""

import json
import ipaddress


# ---------------------------------------------------------------------------
#  Validators / utilities
# ---------------------------------------------------------------------------

def is_valid_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def is_valid_json(data: str) -> bool:
    try:
        json.loads(data)
        return True
    except (ValueError, TypeError):
        return False


def make_interface_string(intf: str) -> str:
    return f'"{intf}"'


# ---------------------------------------------------------------------------
#  Timezone validation
# ---------------------------------------------------------------------------

_TIMEZONES: dict[str, list[str]] = {
    "Africa": [
        "Abidjan", "Accra", "Addis_Ababa", "Algiers", "Asmara", "Bamako", "Bangui", "Banjul",
        "Bissau", "Blantyre", "Brazzaville", "Bujumbura", "Cairo", "Casablanca", "Ceuta",
        "Conakry", "Dakar", "Dar_es_Salaam", "Djibouti", "Douala", "El_Aaiun", "Freetown",
        "Gaborone", "Harare", "Johannesburg", "Juba", "Kampala", "Khartoum", "Kigali",
        "Kinshasa", "Lagos", "Libreville", "Lome", "Luanda", "Lubumbashi", "Lusaka", "Malabo",
        "Maputo", "Maseru", "Mbabane", "Mogadishu", "Monrovia", "Nairobi", "Ndjamena", "Niamey",
        "Nouakchott", "Ouagadougou", "Porto-Novo", "Sao_Tome", "Tripoli", "Tunis", "Windhoek",
    ],
    "America": [
        "Adak", "Anchorage", "Anguilla", "Antigua", "Araguaina",
        "Argentina/Buenos_Aires", "Argentina/Catamarca", "Argentina/Cordoba",
        "Argentina/Jujuy", "Argentina/La_Rioja", "Argentina/Mendoza",
        "Argentina/Rio_Gallegos", "Argentina/Salta", "Argentina/San_Juan",
        "Argentina/San_Luis", "Argentina/Tucuman", "Argentina/Ushuaia",
        "Aruba", "Asuncion", "Atikokan", "Bahia", "Bahia_Banderas", "Barbados", "Belem",
        "Belize", "Blanc-Sablon", "Boa_Vista", "Bogota", "Boise", "Cambridge_Bay",
        "Campo_Grande", "Cancun", "Caracas", "Cayenne", "Cayman", "Chicago", "Chihuahua",
        "Costa_Rica", "Creston", "Cuiaba", "Curacao", "Danmarkshavn", "Dawson",
        "Dawson_Creek", "Denver", "Detroit", "Dominica", "Edmonton", "Eirunepe",
        "El_Salvador", "Fort_Nelson", "Fortaleza", "Glace_Bay", "Godthab", "Goose_Bay",
        "Grand_Turk", "Grenada", "Guadeloupe", "Guatemala", "Guayaquil", "Guyana",
        "Halifax", "Havana", "Hermosillo", "Indiana/Indianapolis", "Indiana/Knox",
        "Indiana/Marengo", "Indiana/Petersburg", "Indiana/Tell_City", "Indiana/Vevay",
        "Indiana/Vincennes", "Indiana/Winamac", "Inuvik", "Iqaluit", "Jamaica", "Juneau",
        "Kentucky/Louisville", "Kentucky/Monticello", "Kralendijk", "La_Paz", "Lima",
        "Los_Angeles", "Lower_Princes", "Maceio", "Managua", "Manaus", "Marigot",
        "Martinique", "Matamoros", "Mazatlan", "Menominee", "Merida", "Metlakatla",
        "Mexico_City", "Miquelon", "Moncton", "Monterrey", "Montevideo", "Montserrat",
        "Nassau", "New_York", "Nipigon", "Nome", "Noronha", "North_Dakota/Beulah",
        "North_Dakota/Center", "North_Dakota/New_Salem", "Ojinaga", "Panama", "Pangnirtung",
        "Paramaribo", "Phoenix", "Port-au-Prince", "Port_of_Spain", "Porto_Velho",
        "Puerto_Rico", "Rainy_River", "Rankin_Inlet", "Recife", "Regina", "Resolute",
        "Rio_Branco", "Santarem", "Santiago", "Santo_Domingo", "Sao_Paulo", "Scoresbysund",
        "Sitka", "St_Barthelemy", "St_Johns", "St_Kitts", "St_Lucia", "St_Thomas",
        "St_Vincent", "Swift_Current", "Tegucigalpa", "Thule", "Thunder_Bay", "Tijuana",
        "Toronto", "Tortola", "Vancouver", "Whitehorse", "Winnipeg", "Yakutat", "Yellowknife",
    ],
    "Antarctica": ["Casey", "Davis", "DumontDUrville", "Macquarie", "Mawson", "McMurdo",
                   "Palmer", "Rothera", "Syowa", "Troll", "Vostok"],
    "Arctic":     ["Longyearbyen"],
    "Asia": [
        "Aden", "Almaty", "Amman", "Anadyr", "Aqtau", "Aqtobe", "Ashgabat", "Baghdad",
        "Bahrain", "Baku", "Bangkok", "Barnaul", "Beirut", "Bishkek", "Brunei", "Chita",
        "Choibalsan", "Colombo", "Damascus", "Dhaka", "Dili", "Dubai", "Dushanbe", "Gaza",
        "Hebron", "Ho_Chi_Minh", "Hong_Kong", "Hovd", "Irkutsk", "Jakarta", "Jayapura",
        "Jerusalem", "Kabul", "Kamchatka", "Karachi", "Kathmandu", "Khandyga", "Kolkata",
        "Krasnoyarsk", "Kuala_Lumpur", "Kuching", "Kuwait", "Macau", "Magadan", "Makassar",
        "Manila", "Muscat", "Nicosia", "Novokuznetsk", "Novosibirsk", "Omsk", "Oral",
        "Phnom_Penh", "Pontianak", "Pyongyang", "Qatar", "Qyzylorda", "Rangoon", "Riyadh",
        "Sakhalin", "Samarkand", "Seoul", "Shanghai", "Singapore", "Srednekolymsk", "Taipei",
        "Tashkent", "Tbilisi", "Tehran", "Thimphu", "Tokyo", "Tomsk", "Ulaanbaatar",
        "Urumqi", "Ust-Nera", "Vientiane", "Vladivostok", "Yakutsk", "Yekaterinburg", "Yerevan",
    ],
    "Atlantic": ["Azores", "Bermuda", "Canary", "Cape_Verde", "Faroe", "Madeira",
                 "Reykjavik", "South_Georgia", "St_Helena", "Stanley"],
    "Australia": ["Adelaide", "Brisbane", "Broken_Hill", "Currie", "Darwin", "Eucla",
                  "Hobart", "Lindeman", "Lord_Howe", "Melbourne", "Perth", "Sydney"],
    "Europe": [
        "Amsterdam", "Andorra", "Astrakhan", "Athens", "Belgrade", "Berlin", "Bratislava",
        "Brussels", "Bucharest", "Budapest", "Busingen", "Chisinau", "Copenhagen", "Dublin",
        "Gibraltar", "Guernsey", "Helsinki", "Isle_of_Man", "Istanbul", "Jersey",
        "Kaliningrad", "Kiev", "Kirov", "Lisbon", "Ljubljana", "London", "Luxembourg",
        "Madrid", "Malta", "Mariehamn", "Minsk", "Monaco", "Moscow", "Oslo", "Paris",
        "Podgorica", "Prague", "Riga", "Rome", "Samara", "San_Marino", "Sarajevo",
        "Simferopol", "Skopje", "Sofia", "Stockholm", "Tallinn", "Tirane", "Ulyanovsk",
        "Uzhgorod", "Vaduz", "Vatican", "Vienna", "Vilnius", "Volgograd", "Warsaw",
        "Zagreb", "Zaporozhye", "Zurich",
    ],
    "Indian": ["Antananarivo", "Chagos", "Christmas", "Cocos", "Comoro", "Kerguelen",
               "Mahe", "Maldives", "Mauritius", "Mayotte", "Reunion"],
    "Pacific": [
        "Apia", "Auckland", "Bougainville", "Chatham", "Chuuk", "Easter", "Efate",
        "Enderbury", "Fakaofo", "Fiji", "Funafuti", "Galapagos", "Gambier", "Guadalcanal",
        "Guam", "Honolulu", "Johnston", "Kiritimati", "Kosrae", "Kwajalein", "Majuro",
        "Marquesas", "Midway", "Nauru", "Niue", "Norfolk", "Noumea", "Pago_Pago", "Palau",
        "Pitcairn", "Pohnpei", "Port_Moresby", "Rarotonga", "Saipan", "Tahiti", "Tarawa",
        "Tongatapu", "Wake", "Wallis",
    ],
    "UTC": [],
}


def check_timezone_settings(timezone: str, location: str) -> bool:
    if timezone not in _TIMEZONES:
        print(f"Available timezones: {', '.join(_TIMEZONES)}")
        return False
    if timezone == "UTC":
        return True
    if location not in _TIMEZONES[timezone]:
        print(f"Available locations in {timezone}: {', '.join(_TIMEZONES[timezone])}")
        return False
    return True


# ---------------------------------------------------------------------------
#  Payload builders (multi-object helpers)
# ---------------------------------------------------------------------------

def build_tacacs_config(*servers: dict) -> str:
    return json.dumps({"host": list(servers)})


def build_snmp_host_config(*hosts) -> str:
    return json.dumps({"snmp:hosts": {"host": [h.get_config(jsn=False) for h in hosts]}})


# ===========================================================================
#  Configuration models
# ===========================================================================

class Image:
    def __init__(self, name=None, url=None, datastore=None, image_type='vm'):
        self.name = name
        self.url = url
        self.datastore = datastore
        self.image_type = image_type

    def get_config(self) -> str:
        if self.image_type == 'vm':
            config = {
                'image': {
                    'name': self.name,
                    'src': self.url,
                    'properties': {'property': {'name': 'placement', 'value': self.datastore}},
                }
            }
        elif self.image_type == 'upgrade':
            config = {
                'image-name': {
                    'name': self.name,
                    'location': f'/data/intdatastore/uploads/{self.name}.iso',
                }
            }
        else:
            raise ValueError(f"Unknown image type: {self.image_type!r}")
        return json.dumps(config)


class Network:
    def __init__(self, name=None, vlan=None, vlan_range=None, trunk=False,
                 bridge="lan-br", sriov=False, native_vlan=1):
        self.name = name
        self.vlan = vlan or []
        self.vlan_range = vlan_range or []
        self.trunk = trunk
        self.bridge = bridge
        self.sriov = sriov
        self.native_vlan = native_vlan

    def get_config(self) -> str:
        return self._get_trunk_config() if self.trunk else self._get_access_config()

    def _get_trunk_config(self) -> str:
        if self.vlan:
            net = {
                'name': self.name, 'vlan': self.vlan, 'trunk': 'true',
                'native-vlan': self.native_vlan, 'bridge': self.bridge, 'sriov': self.sriov,
            }
        elif self.vlan_range:
            net = {
                'name': self.name, 'vlan-ranges': {'vlan-range': self.vlan_range},
                'trunk': 'true', 'native-vlan': self.native_vlan,
                'bridge': self.bridge, 'sriov': self.sriov,
            }
        else:
            raise ValueError("Trunk network requires either vlan or vlan_range")
        return json.dumps({'network': [net]})

    def _get_access_config(self) -> str:
        return json.dumps({'network': [{
            'name': self.name, 'vlan': self.vlan,
            'trunk': 'false', 'bridge': self.bridge, 'sriov': self.sriov,
        }]})


class Switchport:
    def __init__(self, name=None, description=None, mode="access", vlan=666, native_vlan=666,
                 allowed_vlans="666", shutdown=False, interface_type='gigabitEthernet',
                 channel_group=None, channel_mode='on'):
        self.name = name
        self.description = description
        self.mode = mode
        self.vlan = vlan
        self.native = native_vlan
        self.allowed = allowed_vlans
        self.shut = shutdown
        self.type = interface_type
        self.channel = channel_group
        self.channel_mode = channel_mode

    def get_config(self) -> str:
        return self._get_trunk_config() if self.mode == "trunk" else self._get_access_config()

    def _get_access_config(self) -> str:
        swp = {self.type: {
            "name": self.name,
            "description": self.description,
            "switchport": {"mode": "access", "access": {"vlan": self.vlan}},
        }}
        if self.shut:
            swp[self.type]['shutdown'] = ''
        return json.dumps(swp)

    def _get_trunk_config(self) -> str:
        swp = {self.type: {
            "name": self.name,
            "description": self.description,
            "switchport": {
                "mode": "trunk",
                "trunk": {
                    "native": {"vlan": self.native},
                    "allowed": {"vlan": {"vlan-range": self.allowed}},
                },
            },
        }}
        if self.shut:
            swp[self.type]['shutdown'] = ''
        if self.channel:
            swp[self.type]['channel-group'] = [{'cid': self.channel, 'mode': self.channel_mode}]
        return json.dumps(swp)


class Vlan:
    def __init__(self, vlan_id=1):
        self.vlan_id = vlan_id

    def get_config(self) -> str:
        return json.dumps({'vlan': {'vlan-id': self.vlan_id}})


class SystemConfig:
    def __init__(self, hostname='', ip='', mask='', default_gateway='',
                 dns=None, cimc_access='disable'):
        self.hostname = hostname
        self.ip = ip
        self.mask = mask
        self.default_gateway = default_gateway
        self.dns = dns or []
        self.cimc_access = cimc_access

    def get_config(self) -> str:
        return json.dumps({
            "system:settings": {
                "hostname": self.hostname,
                "mgmt": {"ip": {"address": self.ip, "netmask": self.mask}},
                "dns-server": self.dns,
                "default-gw": self.default_gateway,
                "cimc-access": self.cimc_access,
            }
        })


class Vm:
    def __init__(self, name='', **kwargs):
        self.name = name
        for key, value in kwargs.items():
            setattr(self, key, value)

        nic_template = {"nicid": 0, "model": "virtio", "network": ""}
        interface_list = []
        for key, value in kwargs.items():
            if 'NIC' in key and value:
                try:
                    nic = nic_template.copy()
                    nic['nicid'] = int(key[-1])
                    nic['network'] = value
                    interface_list.append(nic)
                except ValueError:
                    raise ValueError(f"NIC argument must end with a digit, got: {key!r}")

        self._config = {
            "deployment": [{
                "name": self.name,
                "vm_group": [{
                    "name": self.name,
                    "image": self.image,
                    "flavor": self.flavor,
                    "vim_vm_name": self.name,
                    "bootup_time": -1,
                    "recovery_wait_time": 0,
                    "interfaces": {"interface": interface_list},
                    "scaling": {"min_active": 1, "max_active": 1},
                    "placement": [{"type": "zone_host", "host": self.datastore}],
                    "recovery_policy": {"action_on_recovery": "REBOOT_ONLY"},
                }],
            }]
        }
        if hasattr(self, 'config_data'):
            extra = json.loads(self.config_data)
            for k, v in extra.items():
                self._config['deployment'][0]['vm_group'][0][k] = v

    def get_config(self) -> str:
        return json.dumps(self._config)


class SnmpGroup:
    def __init__(self, name='', context='', version='', read='', write='', notify='', security=''):
        self.name = name
        self.context = context
        self.version = version
        self.read = read
        self.write = write
        self.notify = notify
        self.security = security

    def get_config(self) -> str:
        return json.dumps({
            "group": {
                "group-name": self.name,
                "group-context-prefix": self.context,
                "group-version": self.version,
                "read": self.read,
                "write": self.write,
                "notify": self.notify,
                "security-level": self.security,
            }
        })


class SnmpUser:
    def __init__(self, name='', version=3, group='', auth_proto='sha', priv_proto='aes', passphrase=''):
        self.name = name
        self.version = version
        self.group = group
        self.auth = auth_proto
        self.priv = priv_proto
        self.passwd = passphrase

    def get_config(self) -> str:
        if self.version == 2:
            return json.dumps({"user-name": self.name, "user-version": 2, "user-group": "SINetMGT"})
        if self.version == 3:
            return json.dumps({
                "user-name": self.name,
                "user-version": 3,
                "user-group": self.group,
                "auth-protocol": self.auth,
                "priv-protocol": self.priv,
                "passphrase": self.passwd,
            })
        raise ValueError(f"Unsupported SNMP version: {self.version}")


class SnmpHost:
    def __init__(self, hostname='', version=3, port=162, security_level='noAuthNoPriv',
                 host_ip_address='', username=''):
        self.hostname = hostname
        self.version = version
        self.port = port
        self.security_level = security_level
        self.host_ip_address = host_ip_address
        self.username = username

    def get_config(self, jsn: bool = True) -> str | dict:
        config = {
            "host-name": self.hostname,
            "host-port": self.port,
            "host-ip-address": self.host_ip_address,
            "host-version": self.version,
            "host-security-level": self.security_level,
            "host-user-name": self.username,
        }
        return json.dumps(config) if jsn else config


class TacacsServer:
    def __init__(self, ip='', secret_key_id='0', shared_secret='', admin_priv='15', oper_priv='11'):
        self.ip = ip
        self.key_id = secret_key_id
        self.shared_secret = shared_secret
        self.admin_priv = admin_priv
        self.oper_priv = oper_priv

    def get_config(self) -> dict:
        return {
            "server": self.ip,
            "secret": {
                "key": self.key_id,
                "encrypted-shared-secret": self.shared_secret,
                "admin-priv": self.admin_priv,
                "oper-priv": self.oper_priv,
            },
        }
