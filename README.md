
# HomeBot: Telegram robot for Hubitat

This script enables a [Telegram](https://telegram.org/) bot to handle commands against devices managed by a [Hubitat](https://hubitat.com/) hub.

## Pre-requisites

* A [Hubitat](https://hubitat.com/) hub
* A device on the same LAN as the Hubitat hub that is capable of running Python scripts, e.g. [Rasbpian](https://www.raspbian.org/) or Windows
* [Python](https://www.python.org/) 3.7 (or later) and pip3 installed on that device
* [Maker API](https://docs.hubitat.com/index.php?title=Maker_API) installed and configured in Hubitat
* A [Telegram](https://telegram.org/) account to interact with the bot
* A Telegram [bot](https://core.telegram.org/bots). Use [BotFather](https://core.telegram.org/bots#6-botfather) to create one

## Setup

* `git clone` the repo or download the source code
* cd into the directory containing the source code
* Copy the `template.config.yaml` file to `config.yaml`
* Modify `config.yaml` by following the instructions in the file
* Run `pip3 install -r requirements.txt` 

## Running

`python3 main.py`

Shorter: `.\main.py` (Windows) or `./main.py` (any other OS)

## Exiting

`Ctrl-C` if running in interactive mode, kill the process otherwise.

## Using the bot

From your Telegram account, write `/h` to the bot to get started.

## Troubleshooting

* Set `logverbosity` to `VERBOSE` in `config.yaml` to get more details
* Ensure the device running the Python script can access the Hubitat's Maker API by trying the `<hubitat.url>/apps/api/<hubitat.appid>/devices?access_token=<hubitat.token>` url from that device (replace placeholders with values from config.yaml)
* If a given device doesn't show up when issuing the `/l` command:
  1. Check that it is included in the list of devices exposed through Hubitat's MakerAPI
  2. Check that the `hubitat.allowed_device_ids` setting in `config.yaml` is either empty or includes the device's id