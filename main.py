#!/bin/python3

from __future__ import annotations  # because raspberry pi is on Python 3.7 and annotations are 3.9


import datetime
from enum import IntEnum

# https://github.com/danielorf/pyhubitat
from pyhubitat import MakerAPI
import logging
from pathlib import Path
import pytz  # timezones
import re

# https://github.com/python-telegram-bot/python-telegram-bot
from telegram import Update, ParseMode
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Filters, Updater
from typing import Union
import yaml

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)


class AccessLevel(IntEnum):
    NONE = 0
    DEVICE = 1
    SECURITY = 2
    ADMIN = 3


class BotUser:
    def __init__(self, id: int, access_level: AccessLevel, user_group: str, device_groups: list) -> None:
        self.id = id
        self.access_level = access_level
        self.user_group = user_group
        self.device_groups = device_groups
        logging.debug(f"User={id}; AccessLevel:={access_level}; UserGroup={self.user_group}.")

    def has_access(self, requested: AccessLevel) -> bool:
        return self.access_level >= requested


class Telegram:
    def __init__(self, conf: dict, hubitat):
        self.hubitat = hubitat
        self.users = {}
        self.rejected_message = conf["rejected_message"]
        for group_name, group_data in conf["user_groups"].items():
            access_level = AccessLevel[group_data["access_level"]]
            device_groups = [hubitat.get_device_group(name) for name in group_data["device_groups"]]
            for id in map(int, group_data["ids"]):
                if id in self.users:
                    raise ValueError(f"User id {id} is referenced in both groups '{group_name}' and '{self.users[id].user_group}'.")
                self.users[id] = BotUser(id, access_level, group_name, device_groups)
        self.updater = Updater(token=conf["token"], use_context=True)
        self.dispatcher = self.updater.dispatcher

    def get_user(self, id: int) -> BotUser:
        return self.users[id]


class Device:
    def __init__(self, device: dict):
        self.id: int = int(device["id"])
        self.label: str = device["label"]
        self.type: str = device["type"]
        self.commands: list[str] = device["commands"]
        self.supported_commands: list[str] = []


class DeviceGroup:
    def __init__(self, name: str, conf: dict, hubitat):
        self.hubitat = hubitat
        self.name = name
        self.allowed_device_ids = set(map(int, conf["allowed_device_ids"]))
        self.rejected_device_ids = set(map(int, conf["rejected_device_ids"]))
        self._devices = None
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

            return len(supported_commands) > 0

        if self._devices is None:
            logging.debug(f"Refreshing device cache for device group '{self.name}'.")
            self._devices = {self.case_hack(device.label): device for device in self.hubitat.get_all_devices() if is_allowed_device(device)}
        return self._devices

    def case_hack(self, name: str) -> str:
        # Gross Hack (tm) because Python doesn't support case comparers for dictionaries
        if self.hubitat.case_insensitive:
            name = name.lower()
        return name

    def get_device(self, name: str) -> dict[str, Device]:
        return self.get_devices().get(self.case_hack(name), None)


class Hubitat:
    def __init__(self, conf: dict):
        hub = f"{conf['url']}apps/api/{conf['appid']}"
        logging.info(f"Connecting to hubitat Maker API app {hub}")
        self.api = MakerAPI(conf["token"], hub)
        self.device_groups = {}
        self._devices_cache = None
        self.case_insensitive = bool(conf["case_insensitive"])
        self.device_aliases = conf["device_aliases"]
        self.he_to_bot_commands = {"on": None, "off": None, "setLevel": "/dim", "open": None, "close": None, "lock": None, "unlock": None}
        # because Python doesn't support case insensitive searches
        # and Hubitats requires exact case, we create a dict{lowercase,requestedcase}
        self.hsm_arm = {x.lower(): x for x in conf["hsm_arm_values"]}
        for name, data in conf["device_groups"].items():
            self.device_groups[name] = DeviceGroup(name, data, self)
        if not self.device_groups:
            raise Exception("At least one device group must be specified in the config file.")

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

        return self._devices_cache

    def get_device(self, name: str, groups: list[DeviceGroup]) -> dict[str, Device]:
        for group in groups:
            ret = group.get_device(name)
            if ret:
                return ret
        return None


class Homebot:
    def __init__(self, telegram: Telegram, hubitat: Hubitat):
        self.telegram = telegram
        self.hubitat = hubitat
        self.list_commands = {AccessLevel.NONE: [], AccessLevel.DEVICE: ["*Device commands*:"], AccessLevel.ADMIN: ["*Admin commands*:"], AccessLevel.SECURITY: ["*Security commands*:"]}

    def send_text(self, update: Update, context: CallbackContext, text: Union[str, list[str]]) -> None:
        self.send_text_or_list(update, context, text, None)

    def send_md(self, update: Update, context: CallbackContext, text: Union[str, list[str]]) -> None:
        self.send_text_or_list(update, context, text, ParseMode.MARKDOWN)

    def send_text_or_list(self, update: Update, context: CallbackContext, text: Union[str, list[str]], parse_mode: ParseMode) -> None:
        if not text:
            return
        if isinstance(text, list):
            text = "\n".join(text)
        context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode=parse_mode)

    def add_command(self, cmd: list, hlp: str, fn, access_level: AccessLevel, params: str = None) -> None:
        helptxt = ""
        for str in cmd:
            if helptxt:
                helptxt = helptxt + ", "
            helptxt = helptxt + "/" + str
            self.telegram.dispatcher.add_handler(CommandHandler(str, fn, Filters.user(self.telegram.users)))
        if params:
            helptxt = helptxt + " `" + params + "`"
        helptxt = helptxt + ": " + hlp
        self.list_commands[access_level].append(helptxt)

    def get_single_arg(self, context: CallbackContext) -> str:
        # lower because Python doesn't support case insensitive searches
        return " ".join(context.args).lower()

    def get_device(self, update: Update, context: CallbackContext) -> Device:
        device_name = self.get_single_arg(context)
        if not device_name:
            self.send_text(update, context, "Device name not specified.")
            return None

        device_groups = self.get_user(update).device_groups
        device = self.hubitat.get_device(device_name, device_groups)
        if device:
            return device

        for alias in self.hubitat.device_aliases:
            pattern = alias[0]
            sub = alias[1]
            new_device_name = re.sub(pattern, sub, device_name)
            logging.debug(f"Trying regex s/{pattern}/{sub}/ => {new_device_name}")
            device = self.hubitat.get_device(new_device_name, device_groups)
            if device:
                return device

        self.send_text(update, context, "Device not found. '/l' to get list of devices.")
        return None

    def markdown_escape(self, text: str) -> str:
        text = re.sub(r"([_*\[\]()~`>\#\+\-=|\.!])", r"\\\1", text)
        text = re.sub(r"\\\\([_*\[\]()~`>\#\+\-=|\.!])", r"\1", text)
        return text

    def get_timezone(self, context: CallbackContext) -> str:
        return context.user_data.get("tz", None)

    def set_timezone(self, context: CallbackContext, value: str) -> None:
        context.user_data["tz"] = value

    def get_user(self, update: Update) -> BotUser:
        return self.telegram.get_user(update.effective_user.id)

    def has_access(self, update: Update, access_level: AccessLevel) -> bool:
        return self.get_user(update).has_access(access_level)

    def get_user_info(self, update: Update) -> str:
        if not update.effective_user:
            return "None"  # e.g., channel_post
        return f"UserId {update.effective_user.id} ({update.effective_user.name})"

    def log_command(self, update: Update, command: str, device: Device = None) -> None:
        if device:
            command = command + " " + device.label
        logging.info(f"{self.get_user_info(update)} is sending command: {command}")

    def request_access(self, update: Update, context: CallbackContext, access_level: AccessLevel) -> None:
        if not self.has_access(update, access_level):
            # user attempting to use admin/device/security command without perm, pretend it doesn't exist
            self.command_unknown(update, context)
            raise PermissionError(f"{self.get_user_info(update)} is attempting level {access_level} command without permission.")

    def device_actuator(self, update: Update, context: CallbackContext, command: Union[str, list], bot_command: str, message: str, access_level=AccessLevel.DEVICE) -> None:
        self.request_access(update, context, access_level)
        device = self.get_device(update, context)
        if device:
            supported_commands = device.supported_commands
            if bot_command not in supported_commands:
                self.send_md(update, context, f"Command {bot_command} not supported by device `{device.label}`.")
                return
            self.log_command(update, bot_command, device)
            if isinstance(command, list):
                self.hubitat.api.send_command(device.id, command[0], command[1])
            else:
                self.hubitat.api.send_command(device.id, command)
            self.send_text(update, context, message.format(device.label))

    def command_device_info(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.ADMIN)
        device = self.get_device(update, context)
        if device:
            info = self.hubitat.api.get_device_info(device.id)
            self.log_command(update, "/info", device)
            self.send_md(update, context, [f"*{k}*: `{v}`" for k, v in info.items()])

    def command_refresh(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.ADMIN)
        self.hubitat.refresh_devices()
        self.send_text(update, context, "Refresh completed.")

    def command_text(self, update: Update, context: CallbackContext) -> None:
        # TODO: make it more interesting by consuming update.message.text
        self.command_help(update, context)

    def command_device_status(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.DEVICE)
        device = self.get_device(update, context)
        if device:
            self.log_command(update, "/status", device)
            status = self.hubitat.api.device_status(device.id)
            text = [f"Status for device *{device.label}*:"]
            if self.has_access(update, AccessLevel.ADMIN):
                text += [f"*{k}*: `{v['currentValue']}` ({v['dataType']})" for k, v in status.items() if v["dataType"] != "JSON_OBJECT"]
            else:
                text += [f"*{k}*: `{v['currentValue']}`" for k, v in status.items() if v["dataType"] != "JSON_OBJECT"]
            self.send_md(update, context, text)

    def get_matching_timezones(self, input: str) -> list[str]:
        input = input.lower()
        return [v for v in pytz.common_timezones if input in v.lower()]

    def command_timezone(self, update: Update, context: CallbackContext) -> None:
        timezone = " ".join(context.args)
        if timezone:
            if timezone in pytz.all_timezones_set:
                self.set_timezone(context, timezone)
                self.send_text(update, context, "Timezone set")
            else:
                hits = self.get_matching_timezones(timezone)
                if not hits:
                    hits = pytz.common_timezones
                hits = hits[0:10]
                self.send_text(update, context, "Invalid timezone. Valid timezones are: " + ", ".join(hits) + ", ...")
        else:
            timezone = self.get_timezone(context)
            if timezone:
                self.send_text(update, context, f"User timezone is: {timezone}.")
            else:
                self.send_text(update, context, "No timezone set for current user. Using UTC.")

    def command_device_last_event(self, update: Update, context: CallbackContext) -> None:
        self.get_device_events(update, context, True)

    def command_device_events(self, update: Update, context: CallbackContext) -> None:
        self.get_device_events(update, context, False)

    def get_device_events(self, update: Update, context: CallbackContext, last_only: bool) -> None:
        self.request_access(update, context, AccessLevel.SECURITY)
        device = self.get_device(update, context)
        if device:
            self.log_command(update, "/events", device)
            events = self.hubitat.api.get_device_events(device.id)

            if len(events) == 0:
                self.send_md(update, context, f"No events for device *{device.label}*")
                return

            tz = self.get_timezone(context)
            tz_text = "UTC"

            if tz:
                tz_text = self.markdown_escape(tz)
                tz = pytz.timezone(tz)

            def convert_date(event_date: str) -> str:
                # event_date is a string in ISO 8601 format
                # e.g. 2022-02-03T04:02:32+0000
                # start by transforming into a real datetime
                event_date = datetime.datetime.strptime(event_date, "%Y-%m-%dT%H:%M:%S%z")
                if tz:
                    # now transform it to the proper tz
                    event_date = event_date.astimezone(tz)
                # and ... convert back to string.
                event_date = event_date.strftime("%Y-%m-%d %H:%M:%S")
                return event_date

            if last_only:
                event = events[0]
                text = [f"Last event for device *{device.label}*:", f"Time: `{convert_date(event['date'])}` ({tz_text})", f"Name: {event['name']}", f"Value: {self.markdown_escape(event['value'])}"]
                self.send_md(update, context, text)
                return

            def row(date, name, value) -> str:
                return f"{date :20}|{name :12}|{value:10}"

            text = [f"Events for device *{device.label}*, timezone {tz_text}:", "```", row("date", "name", "value")]

            for event in events:
                event_date = convert_date(event["date"])
                text.append(row(event_date, event["name"], event["value"]))

            text.append("```")

            self.send_md(update, context, text)

    def command_unknown(self, update: Update, context: CallbackContext) -> None:
        self.send_text(update, context, "Unknown command.")
        self.command_help(update, context)

    def list_devices(self, update: Update, context: CallbackContext, devices: dict[str, Device], title: str):
        self.request_access(update, context, AccessLevel.DEVICE)
        devices_text = []
        if title:
            devices_text.append(title)
        if not devices:
            devices_text.append("No devices.")
        else:
            if self.has_access(update, AccessLevel.ADMIN):
                devices_text += [f"{info.label}: `{info.id}` ({info.type})" for name, info in sorted(devices.items())]
            else:
                devices_text += [info.label for name, info in sorted(devices.items())]
        self.send_md(update, context, devices_text)

    def command_list_devices(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.DEVICE)
        device_groups = self.get_user(update).device_groups
        device_filter = self.get_single_arg(context)
        devices = {}
        for device_group in device_groups:
            for device in device_group.get_devices().values():
                # lower(): Hack because Python doesn't support case-insensitive searches
                if device_filter in device.label.lower():
                    devices[device.label] = device

        self.list_devices(update, context, devices, None)

    def command_list_groups(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.ADMIN)

        group_filter = self.get_single_arg(context)
        for group in self.hubitat.get_device_groups():
            # lower(): Hack because Python doesn't support case-insensitive searches
            if group_filter in group.name.lower():
                self.list_devices(update, context, group.get_devices(), f"Devices in *{group.name}*:")

    def command_help(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.NONE)  # Technically not needed
        self.send_md(update, context, self.list_commands[self.get_user(update).access_level])

    def command_unknown_user(self, update: Update, context: CallbackContext) -> None:
        logging.warning(f"Unknown {self.get_user_info(update)} is attempting to use the bot.")
        self.send_text(update, context, self.telegram.rejected_message)

    def command_device_on(self, update: Update, context: CallbackContext) -> None:
        self.device_actuator(update, context, "on", "/on", "Turned on {}.")

    def command_device_off(self, update: Update, context: CallbackContext) -> None:
        self.device_actuator(update, context, "off", "/off", "Turned off {}.")

    def command_device_open(self, update: Update, context: CallbackContext) -> None:
        self.device_actuator(update, context, "open", "/open", "Opened {}.")

    def command_device_close(self, update: Update, context: CallbackContext) -> None:
        self.device_actuator(update, context, "close", "/close", "Closed {}.")

    def command_device_lock(self, update: Update, context: CallbackContext) -> None:
        self.device_actuator(update, context, "lock", "/lock", "Locked {}.", access_level=AccessLevel.SECURITY)

    def command_device_unlock(self, update: Update, context: CallbackContext) -> None:
        self.device_actuator(update, context, "unlock", "/unlock", "Unlocked {}.", access_level=AccessLevel.SECURITY)

    def command_list_users(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.ADMIN)

        def row(id, isAdmin, userGroup, deviceGroup) -> str:
            return f"{id :10}|{isAdmin :5}|{userGroup :10}|{deviceGroup}"

        text = ["```", row("Id", "Level", "UserGroup", "DeviceGroups"), "----------|-----|----------|-----------"]
        text += [row(u.id, u.access_level, u.user_group, [group.name for group in u.device_groups]) for u in self.telegram.users.values()]
        text.append("```")
        self.send_md(update, context, text)

    def get_percent(self, input: str) -> int:
        percent = -1
        try:
            percent = int(input)
        except ValueError:
            return None
        return percent if 100 >= percent >= 0 else None

    def command_device_dim(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.DEVICE)
        if len(context.args) < 2:
            self.send_text(update, context, "Dim level and device name must be specified.")
            return
        percent = self.get_percent(context.args[0])
        if not percent:
            self.send_text(update, context, "Invalid dim level specified: must be an int between 0 and 100.")
            return
        context.args = context.args[1:]
        self.device_actuator(update, context, ["setLevel", percent], "/dim", "Dimmed {} to " + str(percent) + "%")

    def command_mode(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.SECURITY)
        modes = self.hubitat.api._request_sender("modes").json()
        if len(context.args) > 0:
            # mode change requested
            mode_requested = self.get_single_arg(context)
            for mode in modes:
                if mode["name"].lower() == mode_requested:
                    self.log_command(update, f"/mode {mode['name']}")
                    self.hubitat.api._request_sender(f"modes/{mode['id']}")
                    self.send_text(update, context, "Mode change completed.")
                    return
            self.send_text(update, context, "Unknown mode.")

        text = []
        for mode in modes:
            if mode["active"]:
                text.append(mode["name"] + " (*)")
            else:
                text.append(mode["name"])

        self.send_text(update, context, ", ".join(text))

    def command_hsm(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.SECURITY)
        if len(context.args) > 0:
            # mode change requested
            hsm_requested = self.get_single_arg(context)
            if hsm_requested in self.hubitat.hsm_arm:
                hsm = self.hubitat.hsm_arm[hsm_requested]
                self.log_command(update, f"/arm {hsm}")
                self.hubitat.api._request_sender(f"hsm/{hsm}")
                self.send_text(update, context, "Arm request sent.")
            else:
                self.send_text(update, context, f"Invalid arm state. Supported values: {', '.join(self.hubitat.hsm_arm.values())}.")
        else:
            state = self.hubitat.api._request_sender("hsm").json()
            self.send_text(update, context, f"State: {state['hsm']}")

    def command_device_commands(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.DEVICE)
        device = self.get_device(update, context)
        supported_commands = device.supported_commands
        if supported_commands:
            self.send_md(update, context, f"Supported commands for *{device.label}*: {', '.join(supported_commands)}.")
        else:
            self.send_md(update, context, f"No supported commands for *{device.label}*.")

    def configure(self) -> None:
        dispatcher = self.telegram.dispatcher

        # Reject anyone we don't know
        dispatcher.add_handler(MessageHandler(~Filters.user(self.telegram.users.keys()), self.command_unknown_user))

        self.add_command(["close"], "close device `name`", self.command_device_close, AccessLevel.DEVICE, params="name")
        self.add_command(["commands", "c"], "list supported commands for device `name`", self.command_device_commands, AccessLevel.DEVICE, params="name")
        self.add_command(["dim", "d"], "dim device `name` by `number` percent", self.command_device_dim, AccessLevel.DEVICE, params="number name")
        self.add_command(["events", "e"], "get recent events for device `name`", self.command_device_events, AccessLevel.SECURITY, params="name")
        self.add_command(["groups", "g"], "get device groups, optionally filtering name by `filter`", self.command_list_groups, AccessLevel.ADMIN, params="filter")
        self.add_command(["help", "h"], "display help", self.command_help, AccessLevel.NONE)  # sadly '/?' is not a valid command
        self.add_command(["arm", "a"], "get hsm arm status or arm to `value`", self.command_hsm, AccessLevel.SECURITY, "value")
        self.add_command(["info", "i"], "get info of device `name`", self.command_device_info, AccessLevel.ADMIN, params="name")
        self.add_command(["lastevent", "le"], "get the last event for device `name`", self.command_device_last_event, AccessLevel.SECURITY, params="name")
        self.add_command(["list", "l"], "get devices, optionally filtering name by `filter`", self.command_list_devices, AccessLevel.DEVICE, params="filter")
        self.add_command(["lock"], "lock device `name`", self.command_device_lock, AccessLevel.SECURITY, params="name")
        self.add_command(["mode", "m"], "lists modes or set mode to `value`", self.command_mode, AccessLevel.SECURITY, params="value")
        self.add_command(["off"], "turn off device `name`", self.command_device_off, AccessLevel.DEVICE, params="name")
        self.add_command(["on"], "turn on device `name`", self.command_device_on, AccessLevel.DEVICE, params="name")
        self.add_command(["open"], "open device `name`", self.command_device_open, AccessLevel.DEVICE, params="name")
        self.add_command(["refresh", "r"], "refresh list of devices", self.command_refresh, AccessLevel.ADMIN)
        self.add_command(["status", "s"], "get status of device `name`", self.command_device_status, AccessLevel.DEVICE, params="name")
        self.add_command(["timezone", "tz"], "get timezone or set it to `value`", self.command_timezone, AccessLevel.SECURITY, params="value")
        self.add_command(["unlock"], "lock device `name`", self.command_device_unlock, AccessLevel.SECURITY, params="name")
        self.add_command(["users", "u"], "get users", self.command_list_users, AccessLevel.ADMIN)

        dispatcher.add_handler(MessageHandler(Filters.command, self.command_unknown))
        dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), self.command_text))

        self.list_commands[AccessLevel.DEVICE] += self.list_commands[AccessLevel.NONE]
        self.list_commands[AccessLevel.SECURITY] += self.list_commands[AccessLevel.DEVICE]
        self.list_commands[AccessLevel.ADMIN] += self.list_commands[AccessLevel.SECURITY]

    def run(self) -> None:
        self.telegram.updater.start_polling()
        self.telegram.updater.idle()


try:
    with open(Path(__file__).with_name("config.yaml")) as config_file:
        config = yaml.safe_load(config_file)

        if "telegram" not in config:
            raise ValueError("Invalid config.yaml. Section telegram required.")

        if "hubitat" not in config:
            raise ValueError("Invalid config.yaml. Section hubitat required.")

        if "main" in config:
            conf = config["main"]
            logging.getLogger().setLevel(logging.getLevelName(conf["logverbosity"]))

        hubitat = Hubitat(config["hubitat"])
        telegram = Telegram(config["telegram"], hubitat)

        hal = Homebot(telegram, hubitat)
        hal.configure()
        hal.run()

        exit(0)

except FileNotFoundError as e:
    logging.error("Missing config.yaml file.")
    exit(2)
