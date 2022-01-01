#!/bin/python3

# https://github.com/danielorf/pyhubitat
from pyhubitat import MakerAPI

import logging
from pathlib import Path

import re

# https://github.com/python-telegram-bot/python-telegram-bot
from telegram import Update, ParseMode
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Filters, Updater

import yaml

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)


class BotUser:
    def __init__(self, id: int, is_admin: bool, user_group: str, device_groups: list):
        self.id = id
        self.is_admin = is_admin
        self.user_group = user_group
        self.device_groups = device_groups
        logging.debug(f"User: {id}. IsAdmin: {self.is_admin}. UserGroup: {self.user_group}.")


class Telegram:
    def __init__(self, conf: dict, hubitat):
        self.hubitat = hubitat
        self.users = {}
        self.rejected_message = conf["rejected_message"]
        for group_name, group_data in conf["user_groups"].items():
            is_admin = bool(group_data["is_admin"])
            device_groups = [hubitat.get_device_group(name) for name in group_data["device_groups"]]
            for id in map(int, group_data["ids"]):
                if id in self.users:
                    raise ValueError(f"User id {id} is referenced in both groups '{group_name}' and '{self.users[id].user_group}'.")
                self.users[id] = BotUser(id, is_admin, group_name, device_groups)
        self.updater = Updater(token=conf["token"], use_context=True)
        self.dispatcher = self.updater.dispatcher

    def get_user(self, id: int) -> BotUser:
        return self.users[id]


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

    def get_devices(self) -> dict:

        def is_allowed_device(device) -> bool:
            id = int(device["id"])
            name = f"{device['label']}:{id}"
            if self.allowed_device_ids and not id in self.allowed_device_ids:
                logging.debug(f"Removing device '{name}' because not in allowed list.")
                return False
            if self.rejected_device_ids and id in self.rejected_device_ids:
                logging.debug(f"Removing device '{name}' because in rejected list.")
                return False
            commands = [c['command'] for c in (device['commands'] or [])]

            def has_command(command: str) -> bool:
                if command in commands:
                    return True
                logging.debug(f"Device '{name}' doesn't support command '{command}'.")
                return False

            return has_command("on") and has_command("off")

        if self._devices is None:
            logging.debug(f"Refreshing device cache for device group '{self.name}'.")
            self._devices = {
                self.case_hack(device['label']): device
                for device in self.hubitat.get_all_devices()
                if is_allowed_device(device)}
        return self._devices

    def case_hack(self, name: str) -> str:
        # Gross Hack (tm) because Python doesn't support case comparers for dictionaries
        if self.hubitat.case_insensitive:
            name = name.lower()
        return name

    def get_device(self, name: str) -> dict:
        return self.get_devices().get(self.case_hack(name), None)


class Hubitat:
    def __init__(self, conf: dict):
        hub = f"{conf['url']}apps/api/{conf['appid']}"
        logging.info(f"Connecting to hubitat Maker API app {hub}")
        self.api = MakerAPI(conf["token"], hub)
        self.device_groups = dict()
        self._devices_cache = None
        self.case_insensitive = bool(conf["case_insensitive"])
        self.device_aliases = conf["device_aliases"]
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

    def get_all_devices(self) -> list:
        if self._devices_cache is None:
            logging.info("Refreshing all devices cache")
            self._devices_cache = self.api.list_devices_detailed()

        return self._devices_cache

    def get_device(self, name: str, groups: list) -> dict:
        for group in groups:
            ret = group.get_device(name)
            if ret:
                return ret
        return None


class Homebot:
    def __init__(self, telegram: Telegram, hubitat: Hubitat):
        self.telegram = telegram
        self.hubitat = hubitat
        self.list_commands = ["*User commands*:"]
        self.list_admin_commands = ["*Admin commands*:"]

    def send_text(self, update: Update, context: CallbackContext, text: str) -> None:
        self.send_text_or_list(update, context, text)

    def send_md(self, update: Update, context: CallbackContext, text) -> None:
        self.send_text_or_list(update, context, text, ParseMode.MARKDOWN)

    def send_text_or_list(self, update: Update, context: CallbackContext, text, parse_mode: ParseMode = None) -> None:
        if not text:
            return
        if isinstance(text, list):
            context.bot.send_message(chat_id=update.effective_chat.id, text="\n".join(text), parse_mode=parse_mode)
        else:
            context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode=parse_mode)

    def add_command(self, cmd: list, hlp: str, fn, isAdmin: bool = False, params: str = None) -> None:
        helptxt = ""
        for str in cmd:
            if helptxt:
                helptxt = helptxt + ", "
            helptxt = helptxt + "/" + str
            self.telegram.dispatcher.add_handler(CommandHandler(str, fn, Filters.user(self.telegram.users)))
        if params:
            helptxt = helptxt + " `"+params+"`"
        helptxt = helptxt + ": " + hlp
        if (isAdmin):
            self.list_admin_commands.append(helptxt)
        else:
            self.list_commands.append(helptxt)

    def get_device(self, update: Update, context: CallbackContext) -> dict:
        device_name = ' '.join(context.args)
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

    def get_user(self, update: Update) -> BotUser:
        return self.telegram.get_user(update.effective_user.id)

    def is_admin(self, update: Update, context: CallbackContext = None, log_warning: bool = False) -> bool:
        ret = self.get_user(update).is_admin
        if not ret and log_warning:
            # non admin user attempting to use admin command, pretend it doesn't exist
            logging.warning(f"UserId {update.effective_user.id}, handle {update.effective_user.name} is attempting admin commands.")
            self.command_unknown(update, context)
        return ret

    def device_actuator(self, update: Update, context: CallbackContext, command, message: str) -> None:
        device = self.get_device(update, context)
        if device:
            logging.info(f"User {update.effective_user.id} is sending command {command} to {device['label']}")
            if isinstance(command, list):
                self.hubitat.api.send_command(device["id"], command[0], command[1])
            else:
                self.hubitat.api.send_command(device["id"], command)
            self.send_text(update, context, message.format(device['label']))

    def command_device_info(self, update: Update, context: CallbackContext) -> None:
        if not self.is_admin(update, context=context, log_warning=True):
            return
        device = self.get_device(update, context)
        if device:
            info = self.hubitat.api.get_device_info(device['id'])
            self.send_md(update, context, [f"*{k}*: `{v}`" for k, v in info.items()])

    def command_refresh(self, update: Update, context: CallbackContext) -> None:
        self.hubitat.refresh_devices()
        self.send_text(update, context, "Refresh completed.")

    def command_text(self, update: Update, context: CallbackContext) -> None:
        # TODO: make it more interesting by consuming update.message.text
        self.command_help(update, context)

    def command_device_status(self, update: Update, context: CallbackContext) -> None:
        device = self.get_device(update, context)
        if device:
            status = self.hubitat.api.device_status(device['id'])
            text = [f"Status for device *{device['label']}*:"]
            text += [f"*{k}*: `{v['currentValue']}` ({v['dataType']})" for k, v in status.items()]
            self.send_md(update, context, text)

    def command_unknown(self, update: Update, context: CallbackContext) -> None:
        self.send_text(update, context, "Unknown command.")
        self.command_help(update, context)

    def command_list_devices(self, update: Update, context: CallbackContext) -> None:
        device_groups = self.get_user(update).device_groups
        devices = dict()
        for device_group in device_groups:
            for device in device_group.get_devices().values():
                devices[device['label']] = device

        if not devices:
            self.send_md(update, context, "No devices.")
        else:
            if self.is_admin(update):
                devices_text = [f"*{info['label']}*: `{info['id']}` ({info['type']})" for name, info in sorted(devices.items())]
                self.send_md(update, context, devices_text)
            else:
                self.send_text(update, context, [info['label'] for name, info in sorted(devices.items())])

    def command_help(self, update: Update, context: CallbackContext) -> None:
        if self.is_admin(update):
            self.send_md(update, context, self.list_admin_commands)
        else:
            self.send_md(update, context, self.list_commands)

    def command_unknown_user(self, update: Update, context: CallbackContext) -> None:
        logging.warning(f"Unknown UserId {update.effective_user.id} with handle {update.effective_user.name} is attempting to use the bot.")
        self.send_text(update, context, self.telegram.rejected_message)

    def command_turn_on(self, update: Update, context: CallbackContext) -> None:
        self.device_actuator(update, context, "on", "Turned on {}.")

    def command_turn_off(self, update: Update, context: CallbackContext) -> None:
        self.device_actuator(update, context, "off", "Turned off {}.")

    def command_users(self, update: Update, context: CallbackContext) -> None:
        if self.is_admin(update, context=context, log_warning=True):
            text = [f"Id: {u.id}; Admin: {u.is_admin}; UserGroup: {u.user_group}; DeviceGroups: {[group.name for group in u.device_groups]}" for u in self.telegram.users.values()]
            self.send_md(update, context, text)

    def command_dim(self,  update: Update, context: CallbackContext) -> None:
        if len(context.args) < 2:
            self.send_text("Dim level and device name must be specified.")
            return
        percent = int(context.args[0])
        if percent < 0 or percent > 100:
            self.send_text("Invalid dim level specified.")
            return
        context.args = context.args[1:]
        self.device_actuator(update, context, ["setLevel", percent], "Dimmed {} to "+str(percent)+"%")

    def configure(self) -> None:
        dispatcher = self.telegram.dispatcher

        # Reject anyone we don't know
        dispatcher.add_handler(MessageHandler(~Filters.user(self.telegram.users.keys()), self.command_unknown_user))

        self.add_command(['dim', 'd'], 'dim device <name> by <number> percent', self.command_dim, params="<number> <name>")
        self.add_command(['help', 'h'], 'display help', self.command_help)  # sadly '/?' is not a valid command
        self.add_command(['info', 'i'], 'get info of device `<name>`', self.command_device_info, params="<name>", isAdmin=True)
        self.add_command(['list', 'l'], 'list all devices', self.command_list_devices)
        self.add_command(['on'], 'turn on device `<name>`', self.command_turn_on, params="<name>")
        self.add_command(['off'], 'turn off device `<name>`', self.command_turn_off, params="<name>")
        self.add_command(['refresh', 'r'], 'refresh list of devices', self.command_refresh, isAdmin=True)
        self.add_command(['status', 's'], 'get status of device `<name>`', self.command_device_status, params="<name>")
        self.add_command(['users', 'u'], 'get users', self.command_users, isAdmin=True)

        self.list_admin_commands += self.list_commands

        dispatcher.add_handler(MessageHandler(Filters.command, self.command_unknown))
        dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), self.command_text))

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
