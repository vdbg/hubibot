import logging
import re


class Device:
    def __init__(self, device: dict):
        self.id: int = int(device["id"])
        self.label: str = device["label"]
        self.type: str = device["type"]
        self.commands: list[str] = [c["command"] for c in device["commands"]]
        self.description: str = ""
        self.supported_commands: set[str] = set()

    def __eq__(self, other):
        return isinstance(other, type(self)) and self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __lt__(self, other) -> bool:
        return self.label < other.label


class DeviceGroup:
    def __init__(self, name: str, conf: dict, hubitat):
        self.hubitat = hubitat
        self.name: str = name
        self.allowed_device_ids = set(map(int, conf["allowed_device_ids"]))
        self.rejected_device_ids = set(map(int, conf["rejected_device_ids"]))
        self._devices: dict[str, Device] | None = None
        logging.debug(f"DeviceGroup: {name}. AllowedDeviceIds: {self.allowed_device_ids}. RejectedDeviceIds: {self.rejected_device_ids}.")

    def refresh_devices(self) -> None:
        self._devices = None

    def get_devices(self) -> dict[str, Device]:
        def is_allowed_device(device: Device) -> bool:
            name = f"{device.label}:{device.id}"
            if self.allowed_device_ids and not device.id in self.allowed_device_ids:
                logging.debug(f"Removing device '{name}' because not in allowed list.")
                return False
            if self.rejected_device_ids and device.id in self.rejected_device_ids:
                logging.debug(f"Removing device '{name}' because in rejected list.")
                return False
            supported_commands = set()

            for command in device.commands:
                if command in self.hubitat.he_to_bot_commands:
                    bot_command = self.hubitat.he_to_bot_commands[command] or "/" + command
                    supported_commands.add(bot_command)

            device.supported_commands = supported_commands

            return True

        if self._devices is None:
            logging.debug(f"Refreshing device cache for device group '{self.name}'.")
            self._devices = {self.hubitat.case_hack(device.label): device for device in self.hubitat.get_all_devices() if is_allowed_device(device)}
        return self._devices

    def get_device(self, name: str) -> Device | None:
        return self.get_devices().get(self.hubitat.case_hack(name), None)

    def regex_search_devices(self, pattern: str) -> set[Device]:
        ret = set()
        for key, value in self.get_devices().items():
            if re.fullmatch(pattern, key) is not None:
                ret.add(value)
        return ret
