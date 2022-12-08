from aliases import Aliases
from device import Device, DeviceGroup
import logging
# https://github.com/danielorf/pyhubitat
from pyhubitat import MakerAPI


class Hubitat:
    def __init__(self, conf: dict):
        hub = f"{conf['url'].rstrip('/')}/apps/api/{conf['appid']}"
        logging.info(f"Connecting to hubitat Maker API app {hub}")
        self.api = MakerAPI(conf["token"], hub)
        self.device_groups: dict[str, DeviceGroup] = {}
        self._devices_cache: list[Device] = None
        self.case_insensitive: bool = bool(conf["case_insensitive"])
        self._aliases = Aliases(conf["aliases"], self.case_insensitive)
        self._device_descriptions: dict[int, str] = conf["device_descriptions"]
        self.he_to_bot_commands = {"on": None, "off": None, "setLevel": "/dim", "open": None, "close": None, "lock": None, "unlock": None}
        self._device_name_separator: str = conf["device_name_separator"]
        # because Python doesn't support case insensitive searches
        # and Hubitats requires exact case, we create a dict{lowercase,requestedcase}
        self.hsm_arm: dict[str, str] = {x.lower(): x for x in conf["hsm_arm_values"]}
        for name, data in conf["device_groups"].items():
            self.device_groups[name] = DeviceGroup(name, data, self)
        if not self.device_groups:
            raise Exception("At least one device group must be specified in the config file.")

    def resolve_devices(self, names: str, device_groups: list[DeviceGroup]) -> list[Device]:
        devices = set()
        for name in names.split(self._device_name_separator):
            name = name.strip()
            if not name:
                continue
            device = self._aliases.resolve("device", name, lambda name: self.get_device(name, device_groups))
            if not device:
                return set()  # all or nothing
            devices.add(device)
        return devices

    def resolve_hsm(self, name: str) -> str:
        return self._aliases.resolve("hsm", name, lambda name: self.hsm_arm.get(name, None))

    def resolve_mode(self, name: str, modes) -> dict[str, str]:
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

    def get_device_groups(self) -> list[str]:
        return self.device_groups.values()

    def get_all_devices(self) -> list[Device]:
        if self._devices_cache is None:
            logging.info("Refreshing all devices cache")
            self._devices_cache = [Device(x) for x in self.api.list_devices_detailed()]

            for device in self._devices_cache:
                device.description = self._device_descriptions.get(device.id)

        return self._devices_cache

    def get_device(self, name: str, groups: list[DeviceGroup]) -> dict[str, Device]:
        for group in groups:
            ret = group.get_device(name)
            if ret:
                return ret
        return None
