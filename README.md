
# HomeBot: Telegram robot for Hubitat

This script enables a [Telegram](https://telegram.org/) bot to handle commands against devices managed by a [Hubitat](https://hubitat.com/) hub.

## Pre-requisites

* A [Hubitat](https://hubitat.com/) hub
* A device on the same LAN as the Hubitat hub that is capable of running Python scripts, e.g. [Rasbpian](https://www.raspbian.org/) or Windows
* [Python](https://www.python.org/) 3.7 (or later) and pip3 installed on that device
* [Maker API](https://docs.hubitat.com/index.php?title=Maker_API) installed and configured in Hubitat
* A [Telegram](https://telegram.org/) account to interact with the bot
* A Telegram [bot](https://core.telegram.org/bots). Use [BotFather](https://core.telegram.org/bots#6-botfather) to create one

## Understanding user and device groups

While three user groups ("admins", "family", "guests") and three device groups ("all","regular","limited") are provided in the template config file as examples, any positive number of user and device groups are supported (names are free-form, alphabetical). For example, a single user could only keep "admins" & "all".

Device groups represent collection of Hubitat devices that can be accessed by user groups. In the template config file "admins" user group has access to "all" device group, "family" to "regular", and "guests" to "limited".

User groups represent collection of Telegram users that have access to device groups. User groups can contain any number of Telegram user ids (those with no user ids are ignored) and reference any number of device groups. Users in a user group marked as admin can also access admin commands, such as `/users`.

A user can only belong in one user group, but a device can belong in multiple device groups and a device group can be referenced by multiple user groups. 

## Setup

* `git clone` the repo or download the source code
* cd into the directory containing the source code
* Copy the `template.config.yaml` file to `config.yaml`
* Modify `config.yaml` by following the instructions in the file
* Run `pip3 install -r requirements.txt` 

## Running

Interactive mode: `python3 main.py`

Shorter: `.\main.py` (Windows) or `./main.py` (any other OS).

As a background process (on non-Windows OS): `python3 main.py > log.txt 2>&1 &`

## Exiting

`Ctrl-C` if running in interactive mode, `kill` the process otherwise.

## Using the bot

From your Telegram account, write `/h` to the bot to get started.

## Troubleshooting

* Set `logverbosity` to `VERBOSE` in `config.yaml` to get more details. Note: this will print Hubitat's token in plain text
* Ensure the device running the Python script can access the Hubitat's Maker API by trying the `<hubitat:url>/apps/api/<hubitat:appid>/devices?access_token=<hubitat:token>` url from that device (replace placeholders with values from config.yaml)
* If a given device doesn't show up when issuing the `/list` command:
  1. Check that it is included in the list of devices exposed through Hubitat's MakerAPI
  2. Check that the `hubitat:device_groups:<name>:allowed_device_ids` setting in `config.yaml` for the device group(s) of the current user is either empty or includes the device's id
  3. If the device was added to MakerAPI after starting the bot, issue the `/refresh` command
  4. Check the device group(s) of the given user with the `/users` command