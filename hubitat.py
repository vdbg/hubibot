from aliases import Aliases
from device import Device, DeviceGroup
import logging

# https://github.com/danielorf/pyhubitat
from pyhubitat import MakerAPI


class Hubitat:
    def __init__(self, conf: dict):
        hub = f"{conf['url'].rstrip('/')}/apps/api/{conf['appid']}"
        if hub == "http://ipaddress/apps/api/0":
            raise ValueError("Hubitat's address and app ID must be set")
        logging.info(f"Connecting to hubitat Maker API app {hub}")
        self.api = MakerAPI(conf["token"], hub)
        self.device_groups: dict[str, DeviceGroup] = {}
        self._devices_cache: list[Device] | None = None
        self.case_insensitive: bool = bool(conf["case_insensitive"])
        self._aliases = Aliases(conf["aliases"], self.case_insensitive)
        self._device_descriptions: dict[int, str] = conf["device_descriptions"]
        self.he_to_bot_commands = {"on": None, "off": None, "setLevel": "/dim", "open": None, "close": None, "lock": None, "unlock": None}
        self._device_name_separator: str = conf["device_name_separator"]
        # because Python doesn't support case insensitive searches
        # and Hubitats requires exact case, we create a dict{lowercase,requestedcase}
        self.hsm_arm: dict[str, str] = {x.lower(): x for x in conf["hsm_arm_values"]}
        enabled_device_groups = conf["enabled_device_groups"]
        if not enabled_device_groups:
            raise ValueError("enabled_device_groups (config file) or HUBIBOT_HUBITAT_ENABLED_DEVICE_GROUPS (env var, cmd line param) must be set.")
        device_groups = {k: conf["device_groups"][k] for k in enabled_device_groups}
        if len(device_groups) != len(enabled_device_groups):
            raise ValueError("not all groups listed in enabled_device_groups are defined.")
        for name, data in device_groups.items():
            self.device_groups[name] = DeviceGroup(name, data, self)
        if not self.device_groups:
            raise Exception("At least one device group must be specified in the config file.")

    def resolve_devices(self, names: str, device_groups: list[DeviceGroup]) -> set[Device]:
        devices = set()
        for name in names.split(self._device_name_separator):
            name = name.strip()
            if not name:
                continue
            devices_to_add = self._aliases.resolve("device", name, lambda name: self.__get_devices(name, device_groups))
            if not devices_to_add:
                return set()  # all or nothing
            devices = devices.union(devices_to_add)
        return devices

    def resolve_hsm(self, name: str) -> str | None:
        return self._aliases.resolve("hsm", name, lambda name: self.hsm_arm.get(name, None))

    def resolve_mode(self, name: str, modes) -> dict[str, str] | None:
        modes_dict = {mode["name"].lower(): mode for mode in modes}
        return self._aliases.resolve("mode", name, lambda name: modes_dict.get(name, None))

    def case_hack(self, name: str) -> str:
        # Gross Hack (tm) because Python doesn't support case comparers for dictionaries
        if self.case_insensitive:
            name = name.lower()
        return name

    def refresh_devices(self) -> None:
        self._devices_cache = None
        for g in self.device_groups.values():
            g.refresh_devices()

    def get_device_group(self, name: str) -> DeviceGroup:
        return self.device_groups[name]

    def get_device_groups(self) -> list[DeviceGroup]:
        return list(self.device_groups.values())

    def get_all_devices(self) -> list[Device]:
        if self._devices_cache is None:
            logging.info("Refreshing all devices cache")
            self._devices_cache = [Device(x) for x in self.api.list_devices_detailed()]

            for device in self._devices_cache:
                device.description = self._device_descriptions.get(device.id, "")

        return self._devices_cache

    def __get_devices(self, name: str, groups: list[DeviceGroup]) -> set[Device]:
        devices = set()
        for group in groups:
            ret = group.get_device(name)
            if ret:
                devices.add(ret)
                return devices

        for group in groups:
            devices = devices.union(group.regex_search_devices(name))
        return devices
