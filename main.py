#! /usr/bin/env python3

from datetime import datetime
from device import Device, DeviceGroup
from hubitat import Hubitat
import logging
import platform
import pytz  # timezones
import re
import sys
import threading

# https://github.com/python-telegram-bot/python-telegram-bot
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from accesslevel import AccessLevel
from telegram_wrapper import Telegram, TelegramUser
from typing import Union
from config import Config

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)


class HubiBot:
    def __init__(self, telegram: Telegram, hubitat: Hubitat, default_timezone: str):
        self.telegram = telegram
        self.hubitat = hubitat
        self.default_timezone = default_timezone
        self.list_commands = {AccessLevel.NONE: [], AccessLevel.DEVICE: ["*Device commands*:"], AccessLevel.ADMIN: ["*Admin commands*:"], AccessLevel.SECURITY: ["*Security commands*:"]}

    async def send_text(self, update: Update, context: CallbackContext, text: Union[str, list[str]]) -> None:
        await self.send_text_or_list(update, context, text, None)

    async def send_md(self, update: Update, context: CallbackContext, text: Union[str, list[str]]) -> None:
        await self.send_text_or_list(update, context, text, ParseMode.MARKDOWN)

    async def send_text_or_list(self, update: Update, context: CallbackContext, text: Union[str, list[str]], parse_mode: str | None) -> None:
        if not text:
            return
        if isinstance(text, list):
            text = "\n".join(text)
        chat_id = update.effective_chat.id if update.effective_chat else None
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
        except Exception as e:
            if parse_mode == ParseMode.MARKDOWN:
                logging.error(f"Unable to send message; possibly Markdown issue due to caller not using markdown_escape(). Trying again with formatting disabled.", exc_info=e)
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=None)
            else:
                raise

    def add_command(self, cmd: list, hlp: str, fn, access_level: AccessLevel, params: str = "") -> None:
        helptxt = ""
        for str in cmd:
            if helptxt:
                helptxt = helptxt + ", "
            helptxt = helptxt + "/" + str
            self.telegram.application.add_handler(CommandHandler(str, fn, self.get_user_filter()))
        if params:
            helptxt = helptxt + " `" + params + "`"
        helptxt = helptxt + ": " + hlp
        self.list_commands[access_level].append(helptxt)

    def get_single_arg(self, context: CallbackContext) -> str:
        return "" if not context.args else self.hubitat.case_hack(" ".join(context.args))

    async def get_devices(self, update: Update, context: CallbackContext) -> set[Device]:
        device_name = self.get_single_arg(context)
        if not device_name:
            await self.send_text(update, context, "Device name not specified.")
            return set()

        devices = self.hubitat.resolve_devices(device_name, self.get_user(update).device_groups)

        if not devices:
            await self.send_text(update, context, "Device not found. '/l' to get list of devices.")

        return devices

    def markdown_escape(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"([_*\[\]()~`>\#\+\-=|\.!])", r"\\\1", text)
        text = re.sub(r"\\\\([_*\[\]()~`>\#\+\-=|\.!])", r"\1", text)
        return text

    def get_timezone(self, context: CallbackContext) -> str:
        return context.user_data.get("tz", "") if context.user_data else ""

    def set_timezone(self, context: CallbackContext, value: str) -> None:
        context.user_data["tz"] = value

    def get_user(self, update: Update) -> TelegramUser:
        if not update.effective_user:
            logging.warning("How did a nobody get through?")
            return TelegramUser(-1, AccessLevel.NONE, "", list())
        return self.telegram.get_user(update.effective_user.id)

    def has_access(self, update: Update, access_level: AccessLevel) -> bool:
        return self.get_user(update).has_access(access_level)

    def get_user_info(self, update: Update) -> str:
        if not update.effective_user:
            return "None"  # e.g., channel_post
        return f"UserId {update.effective_user.id} ({update.effective_user.name})"

    def log_command(self, update: Update, command: str, device: Device | None = None) -> None:
        if device:
            command = command + " " + device.label
        logging.info(f"{self.get_user_info(update)} is sending command: {command}")

    def request_access(self, update: Update, context: CallbackContext, access_level: AccessLevel) -> None:
        if not self.has_access(update, access_level):
            # user attempting to use admin/device/security command without perm, pretend it doesn't exist
            self.command_unknown(update, context)
            raise PermissionError(f"{self.get_user_info(update)} is attempting level {access_level} command without permission.")

    async def device_actuator(self, update: Update, context: CallbackContext, command: Union[str, list], bot_command: str, message: str, access_level=AccessLevel.DEVICE) -> None:
        self.request_access(update, context, access_level)
        for device in await self.get_devices(update, context):
            supported_commands = device.supported_commands
            if bot_command not in supported_commands:
                await self.send_md(update, context, f"Command {bot_command} not supported by device `{device.label}`.")
                await self.send_md(update, context, f"Supported commands are: `{ '`, `'.join(supported_commands) }`.")
                continue
            self.log_command(update, bot_command, device)
            if isinstance(command, list):
                self.hubitat.api.send_command(device.id, command[0], command[1])
            else:
                self.hubitat.api.send_command(device.id, command)
            await self.send_text(update, context, message.format(device.label))

    async def command_device_info(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.DEVICE)
        for device in await self.get_devices(update, context):
            info = self.hubitat.api.get_device_info(device.id)
            self.log_command(update, "/info", device)
            info["supported_commands"] = ", ".join(device.supported_commands)
            if not self.has_access(update, AccessLevel.ADMIN):
                info = {"label": info["label"], "supported_commands": info["supported_commands"]}
            if device.description:
                info["description"] = device.description
            await self.send_md(update, context, [f"*{k}*: `{v}`" for k, v in info.items()])

    async def command_refresh(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.ADMIN)
        self.hubitat.refresh_devices()
        await self.send_text(update, context, "Refresh completed.")

    async def command_text(self, update: Update, context: CallbackContext) -> None:
        # TODO: make it more interesting by consuming update.message.text
        await self.command_help(update, context)

    async def command_device_status(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.DEVICE)
        for device in await self.get_devices(update, context):
            self.log_command(update, "/status", device)
            status = self.hubitat.api.device_status(device.id)
            text = [f"Status for *{device.label}*:"]
            if self.has_access(update, AccessLevel.ADMIN):
                text += [f"*{k}*: `{v['currentValue']}` ({v['dataType']})" for k, v in status.items() if v["dataType"] != "JSON_OBJECT"]
            else:
                text += [f"*{k}*: `{v['currentValue']}`" for k, v in status.items() if v["dataType"] != "JSON_OBJECT"]
            await self.send_md(update, context, text)

    def get_matching_timezones(self, input: str) -> list[str]:
        input = input.lower()
        return [v for v in pytz.common_timezones if input in v.lower()]

    async def command_timezone(self, update: Update, context: CallbackContext) -> None:
        timezone = " ".join(context.args) if context.args else ""
        if timezone:
            if timezone in pytz.all_timezones_set:
                self.set_timezone(context, timezone)
                await self.send_text(update, context, "Timezone set")
            else:
                hits = self.get_matching_timezones(timezone)
                if not hits:
                    hits = pytz.common_timezones
                hits = hits[0:10]
                await self.send_text(update, context, "Invalid timezone. Valid timezones are: " + ", ".join(hits) + ", ...")
        else:
            timezone = self.get_timezone(context)
            if timezone:
                await self.send_text(update, context, f"User timezone is: {timezone}.")
            else:
                await self.send_text(update, context, f"No timezone set for current user. Default timezone is {self.default_timezone}.")

    async def command_device_last_event(self, update: Update, context: CallbackContext) -> None:
        await self.get_device_events(update, context, True)

    async def command_device_events(self, update: Update, context: CallbackContext) -> None:
        await self.get_device_events(update, context, False)

    async def get_device_events(self, update: Update, context: CallbackContext, last_only: bool) -> None:
        self.request_access(update, context, AccessLevel.SECURITY)
        for device in await self.get_devices(update, context):
            self.log_command(update, "/events", device)
            events = self.hubitat.api.get_device_events(device.id)

            if len(events) == 0:
                await self.send_md(update, context, f"No events for *{device.label}*")
                continue

            tz_text = self.get_timezone(context)
            if not tz_text:
                tz_text = self.default_timezone
            tz = pytz.timezone(tz_text)
            tz_text = self.markdown_escape(tz_text)

            def convert_date(event_date: str) -> str:
                # event_date is a string in ISO 8601 format
                # e.g. 2022-02-03T04:02:32+0000
                # start by transforming into a real datetime
                event_datetime = datetime.strptime(event_date, "%Y-%m-%dT%H:%M:%S%z")
                # now transform it to the proper tz
                event_datetime = event_datetime.astimezone(tz)
                # and ... convert back to string.
                event_date = event_datetime.strftime("%Y-%m-%d %H:%M:%S")
                return event_date

            if last_only:
                event = events[0]
                text = [f"Last event for *{device.label}*:", f"Time: `{convert_date(event['date'])}` ({tz_text})", f"Name: {event['name']}", f"Value: {self.markdown_escape(event['value'])}"]
                await self.send_md(update, context, text)
                continue

            def row(date, name, value) -> str:
                return f"{date :20}|{name :12}|{value or '':10}"

            text = [f"Events for *{device.label}*, timezone {tz_text}:", "```", row("date", "name", "value")]

            for event in events:
                event_date = convert_date(event["date"])
                text.append(row(event_date, event["name"], event["value"]))

            text.append("```")

            await self.send_md(update, context, text)

    async def command_unknown(self, update: Update, context: CallbackContext) -> None:
        await self.send_text(update, context, "Unknown command.")
        await self.command_help(update, context)

    async def list_devices(self, update: Update, context: CallbackContext, devices: list[Device], title: str | None):
        self.request_access(update, context, AccessLevel.DEVICE)
        devices_text = []

        def get_description(device: Device) -> str:
            if device.description:
                return ": " + self.markdown_escape(device.description)
            else:
                return ""

        if title:
            devices_text.append(title)
        if not devices:
            devices_text.append("No devices.")
        else:
            devices.sort()
            if self.has_access(update, AccessLevel.ADMIN):
                devices_text += [f"{self.markdown_escape(info.label)}: `{info.id}` ({info.type}) {self.markdown_escape(info.description)}" for info in devices]
            else:
                devices_text += [f"{self.markdown_escape(info.label)} {get_description(info)}" for info in devices]
        await self.send_md(update, context, devices_text)

    async def command_list_devices(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.DEVICE)
        device_groups: list[DeviceGroup] = self.get_user(update).device_groups
        device_filter: str = self.get_single_arg(context)
        devices = set()
        for device_group in device_groups:
            for device in device_group.get_devices().values():
                if device_filter in self.hubitat.case_hack(device.label):
                    devices.add(device)

        await self.list_devices(update, context, list(devices), None)

    async def command_regex_list_devices(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.DEVICE)
        device_groups: list[DeviceGroup] = self.get_user(update).device_groups
        device_filter: str = self.get_single_arg(context)
        devices = self.hubitat.resolve_devices(device_filter, device_groups)
        await self.list_devices(update, context, list(devices), None)

    async def command_list_groups(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.ADMIN)

        group_filter = self.get_single_arg(context)
        for group in self.hubitat.get_device_groups():
            if group_filter in self.hubitat.case_hack(group.name):
                await self.list_devices(update, context, list(group.get_devices().values()), f"Devices in *{group.name}*:")

    async def command_help(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.NONE)  # Technically not needed
        await self.send_md(update, context, self.list_commands[self.get_user(update).access_level])

    async def command_unknown_user(self, update: Update, context: CallbackContext) -> None:
        logging.warning(f"Unknown {self.get_user_info(update)} is attempting to use the bot.")
        await self.send_text(update, context, self.telegram.rejected_message)

    async def command_device_on(self, update: Update, context: CallbackContext) -> None:
        await self.device_actuator(update, context, "on", "/on", "Turned on {}.")

    async def command_device_off(self, update: Update, context: CallbackContext) -> None:
        await self.device_actuator(update, context, "off", "/off", "Turned off {}.")

    async def command_device_open(self, update: Update, context: CallbackContext) -> None:
        await self.device_actuator(update, context, "open", "/open", "Opened {}.")

    async def command_device_close(self, update: Update, context: CallbackContext) -> None:
        await self.device_actuator(update, context, "close", "/close", "Closed {}.")

    async def command_device_lock(self, update: Update, context: CallbackContext) -> None:
        await self.device_actuator(update, context, "lock", "/lock", "Locked {}.", access_level=AccessLevel.SECURITY)

    async def command_device_unlock(self, update: Update, context: CallbackContext) -> None:
        await self.device_actuator(update, context, "unlock", "/unlock", "Unlocked {}.", access_level=AccessLevel.SECURITY)

    async def command_list_users(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.ADMIN)

        def row(id, isAdmin, userGroup, deviceGroup) -> str:
            return f"{id :10}|{isAdmin :5}|{userGroup :10}|{deviceGroup}"

        text = ["```", row("Id", "Level", "UserGroup", "DeviceGroups"), "----------|-----|----------|-----------"]
        text += [row(u.id, u.access_level, u.user_group, [group.name for group in u.device_groups]) for u in self.telegram.users.values()]
        text.append("```")
        await self.send_md(update, context, text)

    def get_percent(self, input: str) -> int | None:
        percent = -1
        try:
            percent = int(input)
        except ValueError:
            return None
        return percent if 100 >= percent >= 0 else None

    async def command_device_dim(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.DEVICE)
        if not context.args or len(context.args) < 2:
            await self.send_text(update, context, "Dim level and device name must be specified.")
            return
        percent = self.get_percent(context.args[0])
        if not percent:
            await self.send_text(update, context, "Invalid dim level specified: must be an int between 0 and 100.")
            return
        context.args = context.args[1:]
        await self.device_actuator(update, context, ["setLevel", percent], "/dim", "Dimmed {} to " + str(percent) + "%")

    async def command_mode(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.SECURITY)
        modes = self.hubitat.api._request_sender("modes").json()
        mode_requested = self.get_single_arg(context)
        if mode_requested:
            # mode change requested
            mode = self.hubitat.resolve_mode(mode_requested, modes)
            if mode:
                self.log_command(update, f"/mode {mode['name']}")
                self.hubitat.api._request_sender(f"modes/{mode['id']}")
                await self.send_text(update, context, f"Mode changed to {mode['name']}.")
                return
            await self.send_text(update, context, "Unknown mode.")

        text = []
        for mode in modes:
            if mode["active"]:
                text.append(mode["name"] + " (*)")
            else:
                text.append(mode["name"])

        await self.send_text(update, context, ", ".join(text))

    async def command_hsm(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.SECURITY)
        command = self.get_single_arg(context)
        if command:
            # mode change requested
            hsm = self.hubitat.resolve_hsm(command)
            if hsm:
                self.log_command(update, f"/arm {hsm}")
                self.hubitat.api._request_sender(f"hsm/{hsm}")
                await self.send_text(update, context, f"Arm request {hsm} sent.")
            else:
                await self.send_text(update, context, f"Invalid arm state. Supported values: {', '.join(self.hubitat.hsm_arm.values())}.")
        else:
            state = self.hubitat.api._request_sender("hsm").json()
            await self.send_text(update, context, f"State: {state['hsm']}")

    async def command_exit(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.SECURITY)
        keyboard = [
            [
                InlineKeyboardButton("Yes", callback_data="Exit_Yes"),
                InlineKeyboardButton("No", callback_data="Exit_No"),
            ],
            [InlineKeyboardButton("More information", callback_data="Exit_Help")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Are you sure you want to exit the bot?", reply_markup=reply_markup)

    def shutdown_hack(self):
        # this needs to be on a separate thread because otherwise updater.stop() deadlocks
        self.telegram.application.stop()

    async def button_press(self, update: Update, context: CallbackContext) -> None:
        self.request_access(update, context, AccessLevel.SECURITY)

        query = update.callback_query
        await query.answer()

        if query.data == "Exit_Help":
            await query.edit_message_text(text="This will terminate the bot process. To autorestart, use forever if started from command line or '--restart=always' if started in a Docker container.")
            return

        if query.data == "Exit_Yes":
            await query.edit_message_text(text="Terminating the bot.")
            # threading.Thread(target=self.shutdown_hack).start()
            await self.telegram.application.stop()
            return

        if query.data == "Exit_No":
            await query.edit_message_text(text="Not terminating the bot.")
            return

    async def error_handler(self, update: object, context: CallbackContext) -> None:
        logging.error(msg="Exception while handling an update:", exc_info=context.error)
        if type(update) is Update:
            await self.send_text(update, context, "Internal error")

    def get_user_filter(self) -> filters.User:
        return filters.User(list(self.telegram.users.keys()))

    def configure(self) -> None:
        application = self.telegram.application

        # Reject anyone we don't know
        application.add_handler(MessageHandler(~self.get_user_filter(), self.command_unknown_user))

        self.add_command(["close"], "close device `name`", self.command_device_close, AccessLevel.DEVICE, params="name")
        self.add_command(["dim", "d", "level"], "set device `name` to `number` percent", self.command_device_dim, AccessLevel.DEVICE, params="number name")
        self.add_command(["events", "e"], "get recent events for device `name`", self.command_device_events, AccessLevel.SECURITY, params="name")
        self.add_command(["exit", "x"], "terminates the robot", self.command_exit, AccessLevel.ADMIN)
        self.add_command(["groups", "g"], "get device groups, optionally filtering name by `filter`", self.command_list_groups, AccessLevel.ADMIN, params="filter")
        self.add_command(["help", "h"], "display help", self.command_help, AccessLevel.NONE)  # sadly '/?' is not a valid command
        self.add_command(["arm", "a"], "get hsm arm status or arm to `value`", self.command_hsm, AccessLevel.SECURITY, "value")
        self.add_command(["info", "i"], "get info of device `name`", self.command_device_info, AccessLevel.DEVICE, params="name")
        self.add_command(["lastevent", "le"], "get the last event for device `name`", self.command_device_last_event, AccessLevel.SECURITY, params="name")
        self.add_command(["list", "l"], "get devices, optionally filtering name by `filter`", self.command_list_devices, AccessLevel.DEVICE, params="filter")
        self.add_command(["regex", "rl"], "get devices using regex `filter`", self.command_regex_list_devices, AccessLevel.DEVICE, params="filter")
        self.add_command(["lock"], "lock device `name`", self.command_device_lock, AccessLevel.SECURITY, params="name")
        self.add_command(["mode", "m"], "lists modes or set mode to `value`", self.command_mode, AccessLevel.SECURITY, params="value")
        self.add_command(["off"], "turn off device `name`", self.command_device_off, AccessLevel.DEVICE, params="name")
        self.add_command(["on"], "turn on device `name`", self.command_device_on, AccessLevel.DEVICE, params="name")
        self.add_command(["open"], "open device `name`", self.command_device_open, AccessLevel.DEVICE, params="name")
        self.add_command(["refresh", "r"], "refresh list of devices", self.command_refresh, AccessLevel.ADMIN)
        self.add_command(["status", "s"], "get status of device `name`", self.command_device_status, AccessLevel.DEVICE, params="name")
        self.add_command(["timezone", "tz"], "get timezone or set it to `value`", self.command_timezone, AccessLevel.SECURITY, params="value")
        self.add_command(["unlock"], "unlock device `name`", self.command_device_unlock, AccessLevel.SECURITY, params="name")
        self.add_command(["users", "u"], "get users", self.command_list_users, AccessLevel.ADMIN)

        application.add_handler(MessageHandler(filters.COMMAND, self.command_unknown))
        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self.command_text))
        application.add_handler(CallbackQueryHandler(self.button_press))
        application.add_error_handler(self.error_handler)

        self.list_commands[AccessLevel.DEVICE] += self.list_commands[AccessLevel.NONE]
        self.list_commands[AccessLevel.SECURITY] += self.list_commands[AccessLevel.DEVICE]
        self.list_commands[AccessLevel.ADMIN] += self.list_commands[AccessLevel.SECURITY]

    def run(self) -> None:
        self.telegram.application.run_polling()


SUPPORTED_PYTHON_MAJOR = 3
SUPPORTED_PYTHON_MINOR = 11

if sys.version_info < (SUPPORTED_PYTHON_MAJOR, SUPPORTED_PYTHON_MINOR):
    raise Exception(f"Python version {SUPPORTED_PYTHON_MAJOR}.{SUPPORTED_PYTHON_MINOR} or later required. Current version: {platform.python_version()}.")

try:
    config = Config("config.yaml", "hubibot", sys.argv[1:]).load()

    conf = config["main"]
    logging.getLogger().setLevel(logging.getLevelName(conf["logverbosity"]))
    default_timezone = conf["default_timezone"]
    logging.debug(f"CONFIG: {config}")
    hubitat = Hubitat(config["hubitat"])
    telegram = Telegram(config["telegram"], hubitat)

    hal = HubiBot(telegram, hubitat, default_timezone)
    hal.configure()
    hal.run()

    exit(0)

except FileNotFoundError as e:
    logging.error(f"Missing {e.filename}.")
    exit(2)
