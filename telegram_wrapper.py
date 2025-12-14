from accesslevel import AccessLevel
from device import DeviceGroup
from hubitat import Hubitat
import logging
from telegram.ext import Application


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
        self.start_message: str = conf["start_message"]
        self.nobody = TelegramUser(-1, AccessLevel.NONE, "nobody", []) # default user for unknown ids
        enabled_user_groups = conf["enabled_user_groups"]
        if not enabled_user_groups:
            raise ValueError("enabled_user_groups (config file) or HUBIBOT_TELEGRAM_ENABLED_USER_GROUPS (env var, cmd line param) must be set.")
        user_groups = {k: conf["user_groups"][k] for k in enabled_user_groups}
        if len(user_groups) != len(enabled_user_groups):
            raise ValueError("not all groups listed in enabled_user_groups are defined.")
        for group_name, group_data in user_groups.items():
            access_level = AccessLevel[group_data["access_level"]]
            device_group_names = group_data["device_groups"]
            for device_group in device_group_names:
                if device_group not in hubitat.device_groups:
                    raise ValueError(f"Device group '{device_group}' listed in user group '{group_name}' not defined in hubitat settings")
            device_groups = [hubitat.get_device_group(name) for name in device_group_names]
            ids = list(map(int, group_data["ids"]))
            if not ids:
                raise ValueError(f"ids list for Telegram user group '{group_name}' must be set.")
            for id in ids:
                if id in self.users:
                    raise ValueError(f"User id {id} is referenced in both groups '{group_name}' and '{self.users[id].user_group}'.")
                self.users[id] = TelegramUser(id, access_level, group_name, device_groups)

        self.application = Application.builder().token(conf["token"]).build()

    def get_user(self, id: int) -> TelegramUser:
        # Return a default non-authorized user if id not present to avoid KeyError in callers
        user = self.users.get(id)
        if user is None:
            logging.error(f"Requested Telegram user id {id} not found in configured users.")
            return self.nobody
        return user
