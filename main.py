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


class Telegram:
    def __init__(self, conf: dict):
        self.updater = Updater(token=conf["token"], use_context=True)
        self.dispatcher = self.updater.dispatcher
        self.allowed_users = conf["allowed_users_ids"]
        for user in self.allowed_users:
            logging.debug(f"Allowed user: {user}")
        self.rejected_message = conf["rejected_message"]


class Hubitat:
    def __init__(self, conf: dict):
        hub = f"{conf['url']}apps/api/{conf['appid']}"
        logging.info(f"Connecting to hubitat Maker API app {hub}")
        self.api = MakerAPI(conf["token"], hub)
        self.allowed_device_ids = set(map(int, conf["allowed_device_ids"]))
        self.rejected_device_ids = set(map(int, conf["rejected_device_ids"]))
        self._devices_cache = None
        self._devices = None
        self.case_insensitive = conf["case_insensitive"]
        logging.debug(f"Allowed device ids: {self.allowed_device_ids}")
        logging.debug(f"Rejected device ids: {self.rejected_device_ids}")
        self.device_aliases = conf["device_aliases"]

    def refresh_devices(self) -> None:
        self._devices = None
        self._devices_cache = None

    def get_devices(self) -> dict:
        if self._devices_cache is None:
            logging.info("Refreshing device cache")
            self._devices_cache = self.api.list_devices_detailed()

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
            self._devices = {
                self.case_hack(device['label']): device
                for device in self._devices_cache
                if is_allowed_device(device)}
        return self._devices

    def case_hack(self, name: str) -> str:
        # Gross Hack (tm) because Python doesn't support case comparers for dictionaries
        if self.case_insensitive:
            name = name.lower()
        return name

    def get_device(self, name: str) -> dict:
        return self.get_devices().get(self.case_hack(name), None)


class Homebot:
    def __init__(self, telegram: Telegram, hubitat: Hubitat):
        self.telegram = telegram
        self.hubitat = hubitat
        self.list_commands = []

    def send_text(self, update: Update, context: CallbackContext, text: str) -> None:
        if text:
            context.bot.send_message(chat_id=update.effective_chat.id, text=text)

    def send_md(self, update: Update, context: CallbackContext, text: str = None, list: list = None) -> None:
        if text:
            context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode=ParseMode.MARKDOWN)
        if list:
            context.bot.send_message(chat_id=update.effective_chat.id, text="\n".join(list), parse_mode=ParseMode.MARKDOWN)

    def add_command(self, cmd: list, hlp: str, fn) -> None:
        helptxt = ""
        for str in cmd:
            if helptxt:
                helptxt = helptxt + ", "
            helptxt = helptxt + "/" + str
            self.telegram.dispatcher.add_handler(CommandHandler(str, fn, Filters.user(self.telegram.allowed_users)))
        helptxt = helptxt + ": " + hlp
        self.list_commands.append(helptxt)

    def get_device(self, update: Update, context: CallbackContext) -> dict:
        device_name = ' '.join(context.args)
        if not device_name:
            self.send_text(update, context, "Device name not specified.")
            return None

        device = self.hubitat.get_device(device_name)
        if device is None:
            for alias in self.hubitat.device_aliases:
                pattern = alias[0]
                sub = alias[1]
                new_device_name = re.sub(pattern, sub, device_name)
                logging.debug(f"Trying regex s/{pattern}/{sub}/ => {new_device_name}")
                device = self.hubitat.get_device(new_device_name)
                if not device is None:
                    self.send_text(update, context, f"Using device {device['label']}.")
                    return device

            self.send_text(update, context, "Device not found. '/l' to get list of devices.")

        return device

    def send_text_done(self, update: Update, context: CallbackContext) -> None:
        self.send_text(update, context, "Done.")

    def device_actuator(self, update: Update, context: CallbackContext, command: str) -> None:
        device = self.get_device(update, context)
        if not device is None:
            self.hubitat.api.send_command(device["id"], command)
            self.send_text_done(update, context)

    def command_device_info(self, update: Update, context: CallbackContext) -> None:
        device = self.get_device(update, context)
        if not device is None:
            info = self.hubitat.api.get_device_info(device['id'])
            text = []
            for k, v in info.items():
                text.append(f"*{k}*: `{v}`")
            self.send_md(update, context, list=text)

    def command_refresh(self, update: Update, context: CallbackContext) -> None:
        self.hubitat.refresh_devices()
        self.send_text_done(update, context)

    def command_echo(self, update: Update, context: CallbackContext) -> None:
        # TODO: make it a real command
        self.send_text(update, context, update.message.text)

    def command_device_status(self, update: Update, context: CallbackContext) -> None:
        device = self.get_device(update, context)
        if not device is None:
            status = self.hubitat.api.device_status(device['id'])
            text = []
            for k, v in status.items():
                text.append(f"*{k}*: `{v['currentValue']}` ({v['dataType']})")
            self.send_md(update, context, list=text)

    def command_unknown(self, update: Update, context: CallbackContext) -> None:
        self.send_text(update, context, "Unknown command.")
        self.command_help(update, context)

    def command_list_devices(self, update: Update, context: CallbackContext) -> None:
        devices_text = []
        devices_text.append("Available devices:")
        for name, info in sorted(self.hubitat.get_devices().items()):
            devices_text.append(f"*{info['label']}*: `{info['id']}` ({info['type']})")

        self.send_md(update, context, list=devices_text)

    def command_help(self, update: Update, context: CallbackContext) -> None:
        self.send_text(update, context, "Available commands:\n" + "\n".join(self.list_commands))

    def command_unknown_user(self, update: Update, context: CallbackContext) -> None:
        self.send_text(update, context, self.telegram.rejected_message)

    def command_turn_on(self, update: Update, context: CallbackContext) -> None:
        self.device_actuator(update, context, "on")

    def command_turn_off(self, update: Update, context: CallbackContext) -> None:
        self.device_actuator(update, context, "off")

    def configure(self) -> None:
        dispatcher = self.telegram.dispatcher

        # Reject anyone we don't know
        dispatcher.add_handler(MessageHandler(~Filters.user(self.telegram.allowed_users), self.command_unknown_user))

        self.add_command(['help', 'h'], 'display help', self.command_help)  # sadly '/?' is not a valid command
        self.add_command(['info', 'i'], 'get device info', self.command_device_info)
        self.add_command(['list', 'l'], 'get devices', self.command_list_devices)
        self.add_command(['on'], 'turn on device', self.command_turn_on)
        self.add_command(['off'], 'turn off device', self.command_turn_off)
        self.add_command(['refresh', 'r'], 'refresh list of devices', self.command_refresh)
        self.add_command(['status', 's'], 'get device status', self.command_device_status)

        dispatcher.add_handler(MessageHandler(Filters.command, self.command_unknown))
        dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), self.command_echo))

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

        telegram = Telegram(config["telegram"])
        hubitat = Hubitat(config["hubitat"])

        hal = Homebot(telegram, hubitat)
        hal.configure()
        hal.run()

        exit(0)

except FileNotFoundError as e:
    logging.error("Missing config.yaml file.")
    exit(2)
