[![GitHub issues](https://img.shields.io/github/issues/vdbg/hubibot.svg)](https://github.com/vdbg/hubibot/issues)
[![GitHub license](https://img.shields.io/badge/license-MIT-blue.svg)](https://raw.githubusercontent.com/vdbg/hubibot/main/LICENSE)

# HubiBot: Telegram robot for Hubitat

This program allows a [Telegram](https://telegram.org/) user to issue commands against devices managed by [Hubitat](https://hubitat.com/) through a Telegram bot.

Notable pros compared to alternatives are fine-grained access control and not requiring a VPN.

## Highlights

* Can issue commands to Hubitat devices by talking to a Telegram robot, e.g., `/on Office Light` to turn on the device named "Office Light".
* Can issue different types of command: on/off, lock/unlock, open/close, dim, ...
* Can get the status, capabilities and history of a device.
* Can give multiple names to devices, e.g., `/on hw` doing the same as `/on Hot Water`.
* Can act on multiple devices at once, e.g., `/on hw, office` to turn on both  "Hot Water" and "Office Light".
* Can query and change Hubitat's mode or security monitor state, e.g. `/mode home` and `/arm home`.
* Can expose different sets of devices and permissions to different groups of people, e.g., person managing Hubitat, family members and friends.


## Example of interaction


<img width="479" alt="hubi1" src="https://user-images.githubusercontent.com/1063918/158442236-b4811fc1-a2bc-486b-adf2-3bf8e02ab591.PNG">

<img width="475" alt="hubi2" src="https://user-images.githubusercontent.com/1063918/158442306-eaec3b2b-009d-49d3-bc06-b8652148f80d.PNG">


## Pre-requisites

* A [Hubitat](https://hubitat.com/) hub
* A device, capable of running either Docker containers or Python, that is on the same LAN as the hub e.g., [Raspbian](https://www.raspbian.org/) or Windows
* [Maker API](https://docs.hubitat.com/index.php?title=Maker_API) app installed and configured in Hubitat
* A [Telegram](https://telegram.org/) account to interact with the bot
* A Telegram [bot](https://core.telegram.org/bots). Use [BotFather](https://core.telegram.org/bots#6-botfather) to create one

## Installing

Choose one of these 3 methods.

### Using pre-built Docker image

Dependency: Docker installed.

1. `touch config.yaml`
2. This will fail due to malformed config.yaml. That's intentional :)
   ``sudo docker run --name my_hubibot -v "`pwd`/config.yaml:/app/config.yaml" vdbg/hubibot``
3. `sudo docker cp my_hubibot:/app/template.config.yaml config.yaml`
4. Edit `config.yaml` by following the instructions in the file
5. `sudo docker start my_hubibot -i`
  This will display logging on the command window allowing for rapid troubleshooting. `Ctrl-C` to stop the container if `config.yaml` is changed
7. When done testing the config:
  * `sudo docker container rm my_hubibot`
  * ``sudo docker run -d --name my_hubibot -v "`pwd`/config.yaml:/app/config.yaml" --restart=always --memory=100m vdbg/hubibot``
  * To see logs: `sudo docker container logs -f my_hubibot`

### Using Docker image built from source

Dependency: Docker installed.

1. `git clone https://github.com/vdbg/hubibot.git`
2. `sudo docker build -t hubibot_image hubibot`
3. `cd hubibot`
4. `cp template.config.yaml config.yaml`
5. Edit `config.yaml` by following the instructions in the file
6. Test run: ``sudo docker run --name my_hubibot -v "`pwd`/config.yaml:/app/config.yaml" hubibot_image``
   This will display logging on the command window allowing for rapid troubleshooting. `Ctrl-C` to stop the container if `config.yaml` is changed
7. If container needs to be restarted for testing: `sudo docker start my_hubibot -i`
8. When done testing the config:
  * `sudo docker container rm my_hubibot`
  * ``sudo docker run -d --name my_hubibot -v "`pwd`/config.yaml:/app/config.yaml" --restart=always --memory=100m hubibot_image``
  * To see logs: `sudo docker container logs -f my_hubibot`

### Running directly on the device

Dependency: [Python](https://www.python.org/) 3.9+ and pip3 installed.

1. `git clone https://github.com/vdbg/hubibot.git`
2. `cd hubibot`
3. `cp template.config.yaml config.yaml`
4. Edit `config.yaml` by following the instructions in the file
5. `pip3 install -r requirements.txt`
6. Run the program:
  * Interactive mode: `python3 main.py`
  * Shorter: `.\main.py` (Windows) or `./main.py` (any other OS).
  * As a background process (on non-Windows OS): `python3 main.py > log.txt 2>&1 &`
7. To exit: `Ctrl-C` if running in interactive mode, `kill` the process otherwise.

## Using the bot

From your Telegram account, write `/h` to the bot to get the list of available commands.

## Understanding user and device groups

User and device groups allow for fine-grained access control, for example giving access to different devices to parents, kids, friends and neighbors.

While three user groups ("admins", "family", "guests") and three device groups ("all","regular","limited") are provided in the template config file as examples, any positive number of user and device groups are supported (names are free-form, alphabetical). For example, if only one single user is using the bot, only keeping "admins" user group & "all" device group will suffice.

Device groups represent collection of Hubitat devices that can be accessed by user groups. In the template config file "admins" user group has access to "all" device group, "family" to "regular", and "guests" to "limited".

User groups represent collection of Telegram users that have access to device groups. User groups can contain any number of Telegram user ids (those with no user ids are ignored) and reference any number of device groups. User groups with an `access_level` set to:
* `NONE`: cannot use any commands. Useful to disable a user group.
* `DEVICE`: can use device commands e.g., `/list`, `/regex`, `/on`, `/off`, `/open`, `/close`, `/dim`, `/status`, `/info`.
* `SECURITY`: can use the same commands as `access_level: DEVICE`, and also act on locks with `/lock` & `/unlock` commands, the `/arm` command for [Hubitat Safety Monitor](https://docs.hubitat.com/index.php?title=Hubitat%C2%AE_Safety_Monitor_Interface), the `/mode` command to view and change the mode, the `/events` command to see a device's history, and the `/tz` command to change the timezone for `/events` and `/lastevent`.
* `ADMIN`: can use the same commands as `access_level: SECURITY`, and also admin commands e.g., `/users`, `/groups`, `/refresh`, `/exit`. In addition some commands have more detailed output (e.g., `/list`, `/status`).

A user can only belong to one user group, but a device can belong to multiple device groups and a device group can be referenced by multiple user groups.

## Device name resolution

For all commands taking in device names (such as : `/on name of device`), the app will:

1. Split the input using the `hubitat:device_name_separator` setting in `config.yaml` and remove all leading/trailing spaces. 
  For example, "  office light,   bedroom  " becomes "office light", "bedroom"
2. Look for these in the list of devices Hubitat exposes through MakerAPI that are accessible to the current user (see previous section). 
  If the `hubitat:case_insensitive` setting in `config.yaml` is set to `true`, then the case doesn't need to match.
  For example "office light" will be resolved to "Office Light"
3. For devices not found, the bot will try and interpret the input as a regex. For example, "(Office|Bedroom) Light" will resolve to both "Office Light" and "Bedroom Light"
4. For devices still not found, the transforms in the `hubitat:aliases:device` setting in `config.yaml` are tried in order.
  For example, the app will transform "bedroom" to "bedroom light" and look for that name
5. If there are entries that still could not be found, the entire name resolution process fails.

## Difference between /list and /regex

* `/list` uses the filter as a substring.
* `/regex` uses the filter as a regex.

## Environment Variables

In some docker environments, configuration via environment variables is a common pattern. For example, this docker image can be run on [TrueNAS via Launch Docker Image](https://www.truenas.com/docs/scale/scaletutorials/apps/docker/) and the absolute path to the config file can be set via `HUBIBOT_CONFIG_FILE`.

## Troubleshooting

* Set `main:logverbosity` to `DEBUG` in `config.yaml` to get more details. Note: **Hubitat's token is printed in plain text** when `main:logverbosity` is `DEBUG`
* Ensure the bot was restarted after making changes to `config.yaml`
* Ensure the device running the Python script can access the Hubitat's Maker API by trying to access the `<hubitat:url>/apps/api/<hubitat:appid>/devices?access_token=<hubitat:token>` url from that device (replace placeholders with values from config.yaml)
* If a given device doesn't show up when issuing the `/list` command:
  1. Check that it is included in the list of devices exposed through Hubitat's MakerAPI
  2. Check that the `hubitat:device_groups:<name>:allowed_device_ids` setting in `config.yaml` for the device group(s) of the current user is either empty or includes the device's id
  3. If the device was added to MakerAPI after starting the bot, issue the `/refresh` command
  4. Check the device group(s) of the given user with the `/users` command
  5. Check that the device has a label in Hubitat in addition to a name. The former is used by the bot

## Getting Telegram user Ids

The `config.yaml` file takes user Ids instead of user handles because the later are neither immutable nor unique.

There are two methods for getting a Telegram user Id:
1. Ask that user to write to the @userinfobot to get their user Id
2. Ensure `main:logVerbosity` is set to `WARNING` or higher in `config.yaml` and ask that user to write to the bot. There will be a warning in the logs with that user's Id and handle.

## Authoring

Style:

* From command line: `pip3 install black`,
* In VS code: Settings,
    * Text Editor, Formatting, Format On Save: checked
    * Python, Formatting, Provider: `black`
    * Python, Formatting, Black Args, Add item: `--line-length=200`
