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


class Telegram:
    def __init__(self, conf: dict):
        self.updater = Updater(token=conf["token"], use_context=True)
        self.dispatcher = self.updater.dispatcher
        self.allowed_users = conf["allowed_users_ids"]
        for user in self.allowed_users:
            logging.debug(f"Allowed user: {user}")
        self.rejected_message = conf["rejected_message"]


class homebot:
    def __init__(self, telegram: Telegram, hubitat: MakerAPI, allowed_device_ids: list, rejected_device_ids: list):
        self.telegram = telegram
        self.hubitat = hubitat
        self.list_commands = list()
        self.allowed_device_ids = set(map(int, allowed_device_ids))
        self.rejected_device_ids = set(map(int, rejected_device_ids))
        self._devices_cache = None
        self._devices = None

        logging.debug(f"Allowed device ids: {self.allowed_device_ids}")
        logging.debug(f"Rejected device ids: {self.rejected_device_ids}")

    def get_devices(self) -> dict:
        if self._devices_cache is None:
            logging.info("Refreshing device cache")
            self._devices_cache = self.hubitat.list_devices_detailed()

        def is_allowed_device(device) -> bool:
            id = int(device["id"])
            name = f"{device['label']}:{id}"
            if self.allowed_device_ids and not id in self.allowed_device_ids:
                logging.debug(f"Removing device '{name}' because not in allowed list.")
                return False
            if self.rejected_device_ids and id in self.rejected_device_ids:
                logging.debug(f"Removing device '{name}' because in rejected list.")
                return False
            commands = device["commands"]

            def has_command(command: str) -> bool:
                if commands is None:
                    logging.debug(f"Device '{name}' doesn't support commands")
                    return False

                for c in commands:
                    if c["command"] == command:
                        return True

                logging.debug(f"Device '{name}' doesn't support command '{command}'.")
                return False

            if not has_command("on") or not has_command("off"):
                return False

            return True

        if self._devices is None:
            self._devices = {
                device['label']: device
                for device in self._devices_cache
                if is_allowed_device(device)}
        return self._devices

    def send_text(self, update: Update, context: CallbackContext, text: str) -> None:
        if text:
            context.bot.send_message(chat_id=update.effective_chat.id, text=text)

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

        device = self.get_devices().get(device_name, None)
        if device is None:
            self.send_text(update, context, "Device not found. '/l' to get list of devices.")

        return device

    def device_actuator(self, update: Update, context: CallbackContext, command: str) -> None:
        device = self.get_device(update, context)
        if not device is None:
            self.hubitat.send_command(device["id"], command)

    def command_device_info(self, update: Update, context: CallbackContext) -> None:
        device = self.get_device(update, context)
        if not device is None:
            self.send_text(update, context, device)

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
        for name, info in self.get_devices().items():
            devices_text.append(f"{name}: {info['type']},{info['id']}")

        self.send_text(update, context, "\n".join(devices_text))

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

        self.add_command(['start', 's'], 'something', self.command_start)
        self.add_command(['caps', 'c'], 'caps mode', self.command_caps)
        self.add_command(['help', 'h'], 'display help', self.command_help)  # sadly '/?' is not a valid command
        self.add_command(['info', 'i'], 'get device info', self.command_device_info)
        self.add_command(['list', 'l'], 'get devices', self.command_list_devices)
        self.add_command(['on'], 'turn on device', self.command_turn_on)
        self.add_command(['off'], 'turn off device', self.command_turn_off)

        dispatcher.add_handler(MessageHandler(Filters.command, self.command_unknown))
        dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), self.command_echo))

    def run(self) -> None:
        self.telegram.updater.start_polling()
        self.telegram.updater.idle()


def get_hubitat(conf: dict):
    hub = f"{conf['url']}apps/api/{conf['appid']}"
    logging.info(f"Connecting to hubitat Maker API app {hub}")
    return MakerAPI(conf["token"], hub)


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
        hubitat = get_hubitat(hubitat_conf)
        telegram = Telegram(config["telegram"])

        hal = homebot(telegram, hubitat, hubitat_conf["allowed_device_ids"], hubitat_conf["rejected_device_ids"])
        hal.configure()
        hal.run()

        exit(0)

except FileNotFoundError as e:
    logging.error("Missing config.yaml file.")
    exit(2)
