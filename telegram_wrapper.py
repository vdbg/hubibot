from device import DeviceGroup
from enum import IntEnum
from hubitat import Hubitat
import logging
from telegram.ext import Updater


class AccessLevel(IntEnum):
    NONE = 0
    DEVICE = 1
    SECURITY = 2
    ADMIN = 3


class TelegramUser:
    def __init__(self, id: int, access_level: AccessLevel, user_group: str, device_groups: list[DeviceGroup]) -> None:
        self.id: int = id
        self.access_level: AccessLevel = access_level
        self.user_group: str = user_group
        self.device_groups: list[DeviceGroup] = device_groups
        logging.debug(f"User={id}; AccessLevel:={access_level}; UserGroup={self.user_group}.")

    def has_access(self, requested: AccessLevel) -> bool:
        return self.access_level >= requested


class Telegram:
    def __init__(self, conf: dict, hubitat: Hubitat):
        self.hubitat: Hubitat = hubitat
        self.users: dict[int, TelegramUser] = {}
        self.rejected_message: str = conf["rejected_message"]
        for group_name, group_data in conf["user_groups"].items():
            access_level = AccessLevel[group_data["access_level"]]
            device_groups = [hubitat.get_device_group(name) for name in group_data["device_groups"]]
            for id in map(int, group_data["ids"]):
                if id in self.users:
                    raise ValueError(f"User id {id} is referenced in both groups '{group_name}' and '{self.users[id].user_group}'.")
                self.users[id] = TelegramUser(id, access_level, group_name, device_groups)
        self.updater = Updater(token=conf["token"], use_context=True)
        self.dispatcher = self.updater.dispatcher

    def get_user(self, id: int) -> TelegramUser:
        return self.users[id]
