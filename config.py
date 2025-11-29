import logging
import os
import yaml
import ast
from pathlib import Path
from typing import Callable


class Config:
    def __init__(self, file: str, prefix: str, args: list[str]) -> None:
        self._file = file
        self._prefix = prefix.upper()
        self._args: dict[str, str] = {}
        for arg in args:
            key_value = arg.split("=", 1)
            if len(key_value) != 2 or not key_value[0].startswith(self._prefix):
                logging.warning(f"Ignoring '{arg}' as it's not in the expected format '{self._prefix}_KEY=value'")
                continue
            self._args[key_value[0]] = key_value[1]

    def __load__(self, file: Path) -> dict[str, dict] | None:
        try:
            with open(file, "rb") as config_file:
                return yaml.safe_load(config_file)
        except FileNotFoundError as e:
            logging.warning(f"Missing {e.filename}.")
        return None

    # merge dist src into dst recursively
    def __merge_dict_recursive__(self, src: dict, dst: dict) -> None:
        for k, v in src.items():
            # key doesn't exist in destination or value isn't a dict, overwrite
            if not k in dst or not isinstance(v, dict):
                dst[k] = v
                continue

            # key exist in destination, and value is a dict. Recursively merge
            self.__merge_dict_recursive__(v, dst[k])

    # update values in a dict using a key lookup lambda
    def __merge_vars_recursive__(self, prefix: str, dst: dict, func: Callable[[str], str | None]) -> None:
        for k, v in dst.items():
            key = f"{prefix}_{k}".upper()
            if isinstance(v, dict):
                self.__merge_vars_recursive__(key, v, func)
            else:
                self.__load_val__(dst, k, key, func)

    def __load_val__(self, dst: dict, key_dict: str, key_func: str, func: Callable[[str], str | None]) -> None:
        value: str | None = func(key_func)
        if value:
            try:
                dst[key_dict] = ast.literal_eval(value)
            except Exception:
                # literal_eval may raise ValueError or SyntaxError; treat as string if parsing fails
                logging.warning(f"Treating '{value}' for {key_func} as string")
                dst[key_dict] = value

    # some of the config entries are dynamic, therefore need to manually merge them
    def __load_vars__(self, dst: dict, key_base: str, key_list: str, key_dest_base: str, key_template: str, func: Callable[[str], str | None]) -> None:
        entries = dst[key_base][key_list]
        if not entries:
            return
        target = dst[key_base][key_dest_base]
        key_dest_list: list[str] = list(target[key_template].keys())
        for entry in entries:
            if entry not in target:
                target[entry] = dict()
            for key in key_dest_list:
                lookup = f"{self._prefix}_{key_base}_{key_dest_base}_{entry}_{key}".upper()
                self.__load_val__(target[entry], key, lookup, func)

    # update our config with key lookup lambda
    def __merge_vars__(self, dst: dict, func: Callable[[str], str | None]) -> None:
        self.__merge_vars_recursive__(self._prefix, dst, func)
        # terrible hack - so sad
        self.__load_vars__(dst, "telegram", "enabled_user_groups", "user_groups", "admins", func)
        self.__load_vars__(dst, "hubitat", "enabled_device_groups", "device_groups", "all", func)

    def load(self) -> dict[str, dict]:
        ret = self.__load__(Path(__file__).with_name("template." + self._file))
        if not ret:
            raise Exception(f"File template.{self._file} required.")

        config_file_path = os.getenv(
            f"{self._prefix}_CONFIG_FILE",
            str(Path(__file__).with_name(self._file)),
        )
        logging.info(f"conf file: {config_file_path}")

        # overwrite template with config, if exists
        config = self.__load__(Path(config_file_path))
        if config:
            self.__merge_dict_recursive__(config, ret)

        # overwrite with environment variables, if exist
        self.__merge_vars__(ret, lambda key: os.getenv(key))

        # overwrite with cmd line parameters, if exist
        self.__merge_vars__(ret, lambda key: self._args.get(key))

        return ret
