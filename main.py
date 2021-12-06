#!/bin/python3

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

def start(update: Update, context: CallbackContext):
    context.bot.send_message(chat_id=update.effective_chat.id, text="I'm a bot, please talk to me!")

def echo(update: Update, context: CallbackContext):
    context.bot.send_message(chat_id=update.effective_chat.id, text=update.message.text)

def caps(update: Update, context: CallbackContext):
    text_caps = ' '.join(context.args).upper()
    context.bot.send_message(chat_id=update.effective_chat.id, text=text_caps)

def unknown(update: Update, context: CallbackContext):
    context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, I didn't understand that command.")

def main(conf: dict):
    updater = Updater(token=conf["token"], use_context=True)
    dispatcher = updater.dispatcher

    start_handler = CommandHandler('start', start)
    dispatcher.add_handler(start_handler)

    echo_handler = MessageHandler(Filters.text & (~Filters.command), echo)
    dispatcher.add_handler(echo_handler)

    caps_handler = CommandHandler('caps', caps)
    dispatcher.add_handler(caps_handler)

    unknown_handler = MessageHandler(Filters.command, unknown)
    dispatcher.add_handler(unknown_handler)

    updater.start_polling()
    updater.idle()

try:
    with open(Path(__file__).with_name("config.yaml")) as config_file:
        config = yaml.safe_load(config_file)

        if "telegram" not in config:
            raise ValueError("Invalid config.yaml. Section telegram required.")
        
        if "main" in config:
            conf = config["main"]
            #logging.getLogger().setLevel(logging.getLevelName(conf["logverbosity"]))

        main(config["telegram"])
        exit(0)

except FileNotFoundError as e:
    logging.error("Missing config.yaml file.")
    exit(2)