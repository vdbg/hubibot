#!/bin/python3

# https://github.com/danielorf/pyhubitat
from pyhubitat import MakerAPI

import logging
from pathlib import Path

# https://github.com/python-telegram-bot/python-telegram-bot
from telegram import Update
from telegram.ext import CallbackContext
from telegram.ext import Updater
from telegram.ext import CommandHandler
from telegram.ext import MessageHandler, Filters

import yaml

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)


class homebot:
    def __init__(self, updater: Updater, hubitat: MakerAPI, allowed_users: list, allowed_device_ids: list, rejected_device_ids: list):
        self.updater = updater
        self.hubitat = hubitat
        self.list_commands = list()
        self.allowed_users = allowed_users
        self.allowed_device_ids = set(map(int, allowed_device_ids))
        self.rejected_device_ids = set(map(int, rejected_device_ids))
        self._devices_cache = None
        self._ordered_devices = None

        logging.debug(f"Allowed device ids: {self.allowed_device_ids}")
        logging.debug(f"Rejected device ids: {self.rejected_device_ids}")

    def get_devices(self):
        if self._devices_cache is None:
            logging.info("Refreshing device cache")
            self._devices_cache = self.hubitat.list_devices()
        return self._devices_cache

    def get_ordered_devices(self) -> dict:
        # devices are returned in Id order. Make it alphabetical instead
        if self._ordered_devices is None:
            self._ordered_devices = {
                device['label']: f"{device['type']},{device['id']}"
                for device in self.get_devices()
                if self.is_allowed_device(device)}
        return self._ordered_devices

    def is_allowed_device(self, device) -> bool:
        id = int(device["id"])
        if self.allowed_device_ids and not id in self.allowed_device_ids:
            logging.debug(f"Removing device {device['label']}:{id} because not in allowed list.")
            return False
        if self.rejected_device_ids and id in self.rejected_device_ids:
            logging.debug(f"Removing device {device['label']}:{id} because in rejected list.")
            return False
        return True

    def send_text(self, update: Update, context: CallbackContext, text: str) -> None:
        if text:
            context.bot.send_message(chat_id=update.effective_chat.id, text=text)

    def add_command(self, cmd: list, hlp: str, fn) -> None:
        helptxt = ""
        for str in cmd:
            if helptxt:
                helptxt = helptxt + ", "
            helptxt = helptxt + "/" + str
            self.updater.dispatcher.add_handler(CommandHandler(str, fn, Filters.user(self.allowed_users)))
        helptxt = helptxt + ": " + hlp
        self.list_commands.append(helptxt)

    def command_start(self, update: Update, context: CallbackContext) -> None:
        # TODO: make it a real command
        self.send_text(update, context, "I'm a bot, please talk to me!")

    def command_echo(self, update: Update, context: CallbackContext) -> None:
        # TODO: make it a real command
        self.send_text(update, context, update.message.text)

    def command_caps(self, update: Update, context: CallbackContext) -> None:
        # TODO: make it a real command
        text_caps = ' '.join(context.args).upper()
        self.send_text(update, context, text_caps)

    def command_unknown(self, update: Update, context: CallbackContext) -> None:
        self.send_text(update, context, "Unknown command.")
        self.command_help(update, context)

    def command_list_devices(self, update: Update, context: CallbackContext) -> None:
        devices_text = list()
        devices_text.append("Available devices:")
        for name, info in self.get_ordered_devices().items():
            devices_text.append(f"{name}: {info}")

        self.send_text(update, context, "\n".join(devices_text))

    def command_help(self, update: Update, context: CallbackContext) -> None:
        self.send_text(update, context, "Available commands:\n" + "\n".join(self.list_commands))

    def command_unknown_user(self, update: Update, context: CallbackContext) -> None:
        self.send_text(update, context, "Unauthorized user :p")

    def command_turn_on(self, update: Update, context: CallbackContext) -> None:
        self.send_text(update, context, "TODO")

    def command_turn_off(self, update: Update, context: CallbackContext) -> None:
        self.send_text(update, context, "TODO")

    def configure(self) -> None:
        dispatcher = self.updater.dispatcher

        # Reject anyone we don't know
        self.updater.dispatcher.add_handler(MessageHandler(~Filters.user(self.allowed_users), self.command_unknown_user))

        self.add_command(['start', 's'], 'something', self.command_start)
        self.add_command(['caps', 'c'], 'caps mode', self.command_caps)
        self.add_command(['help', 'h'], 'display help', self.command_help)  # sadly '/?' is not a valid command
        self.add_command(['list', 'l'], 'get devices', self.command_list_devices)
        self.add_command(['on'], 'turn on device', self.command_turn_on)
        self.add_command(['off'], 'turn off device', self.command_turn_off)

        dispatcher.add_handler(MessageHandler(Filters.command, self.command_unknown))
        dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), self.command_echo))

    def run(self) -> None:
        self.updater.start_polling()
        self.updater.idle()


def get_hubitat(conf: dict):
    hub = f"{conf['url']}apps/api/{conf['appid']}"
    logging.info(f"Connecting to hubitat Maker API app {hub}")
    return MakerAPI(conf["token"], hub)


def get_telegram(conf: dict):
    return Updater(token=conf["token"], use_context=True)


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

        hubitat_conf = config["hubitat"]
        telegram_conf = config["telegram"]
        hubitat = get_hubitat(hubitat_conf)
        telegram = get_telegram(telegram_conf)

        allowed_users = telegram_conf["allowed_users_ids"]
        for user in allowed_users:
            logging.debug(f"Allowed user: {user}")

        hal = homebot(telegram, hubitat, allowed_users, hubitat_conf["allowed_device_ids"], hubitat_conf["rejected_device_ids"])
        hal.configure()
        hal.run()

        exit(0)

except FileNotFoundError as e:
    logging.error("Missing config.yaml file.")
    exit(2)
