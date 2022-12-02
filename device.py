import logging


class Device:
    def __init__(self, device: dict):
        self.id: int = int(device["id"])
        self.label: str = device["label"]
        self.type: str = device["type"]
        self.commands: list[str] = device["commands"]
        self.description: str = None
        self.supported_commands: list[str] = []


class DeviceGroup:
    def __init__(self, name: str, conf: dict, hubitat):
        self.hubitat = hubitat
        self.name = name
        self.allowed_device_ids = set(map(int, conf["allowed_device_ids"]))
        self.rejected_device_ids = set(map(int, conf["rejected_device_ids"]))
        self._devices: dict[str, Device] = None
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
            commands = [c["command"] for c in device.commands]
            supported_commands = set()

            for command in commands:
                if command in self.hubitat.he_to_bot_commands:
                    bot_command = self.hubitat.he_to_bot_commands[command] or "/" + command
                    supported_commands.add(bot_command)

            device.supported_commands = supported_commands

            return True

        if self._devices is None:
            logging.debug(f"Refreshing device cache for device group '{self.name}'.")
            self._devices = {self.hubitat.case_hack(device.label): device for device in self.hubitat.get_all_devices() if is_allowed_device(device)}
        return self._devices

    def get_device(self, name: str) -> Device:
        return self.get_devices().get(self.hubitat.case_hack(name), None)
