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

class bot:
    def __init__(self, updater: Updater, hubitat: MakerAPI, allowed_users: list):
        self.updater = updater
        self.hubitat = hubitat
        self.help = list()
        self._devices_cache = None
        self.allowed_users = allowed_users

    def get_devices(self):
        if self._devices_cache is None:
            logging.info("Refreshing device cache")
            self._devices_cache = self.hubitat.list_devices()
        return self._devices_cache
    
    def send_text(self, update: Update, context: CallbackContext, text: str):
        if len(text) > 0:
            context.bot.send_message(chat_id=update.effective_chat.id, text=text)

    def command_start(self, update: Update, context: CallbackContext):
        self.send_text(update, context, "I'm a bot, please talk to me!")

    def command_echo(self, update: Update, context: CallbackContext):
        self.send_text(update, context, update.message.text)

    def command_Caps(self, update: Update, context: CallbackContext):
        text_caps = ' '.join(context.args).upper()
        self.send_text(update, context, text_caps)

    def command_unknows(self, update: Update, context: CallbackContext):
        self.send_text(update, context, "Unknown command.")
        self.command_help(update, context)

    def command_list(self, update: Update, context: CallbackContext):
        devices = self.get_devices()
        for device in devices:
            self.send_text(update, context, f"{device['name']}: {device['type']}")

    def command_help(self, update: Update, context: CallbackContext):
        for k in self.help:
            self.send_text(update, context, k)

    def add_command(self, cmd: list, hlp: str, fn):
        helptxt = ""
        for str in cmd:
            if len(helptxt) != 0:
                helptxt = helptxt + ", "
            helptxt = helptxt + "/" + str
            self.updater.dispatcher.add_handler(CommandHandler(str,fn, Filters.user(self.allowed_users)))
        helptxt = helptxt + ": " + hlp
        self.help.append(helptxt)

    def configure(self):
        dispatcher = self.updater.dispatcher

        self.add_command(['start', 's'],'something', self.command_start)
        self.add_command(['caps', 'c'], 'caps mode', self.command_Caps)
        # sadly '/?' is not a valid command
        self.add_command(['help','h'], 'display help', self.command_help)
        self.add_command(['list','l'], 'get devices', self.command_list)

        unknown_handler = MessageHandler(Filters.command, self.command_unknows)
        dispatcher.add_handler(unknown_handler)

        echo_handler = MessageHandler(Filters.text & (~Filters.command), self.command_echo)
        dispatcher.add_handler(echo_handler)
        
    def run(self):
        self.updater.start_polling()
        self.updater.idle()

def get_hubitat(conf: dict):
    hub = f"{conf['url']}apps/api/{conf['appid']}"
    logging.info(f"Connecting to hubitat app {hub}")
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

        hubitat = get_hubitat(config["hubitat"])
        telegram = get_telegram(config["telegram"])

        allowed_users = config["telegram"]["allowed_users"]
        for user in allowed_users:
            logging.debug(f"Allowed user: {user}")

        mybot = bot(telegram, hubitat, allowed_users)
        mybot.configure()
        mybot.run()

        exit(0)

except FileNotFoundError as e:
    logging.error("Missing config.yaml file.")
    exit(2)