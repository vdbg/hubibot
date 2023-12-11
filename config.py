import logging
import os
import yaml
import ast
from pathlib import Path


class Config:
    def __init__(self, file: str, prefix: str) -> None:
        self._file = file
        self._prefix = prefix.upper()

    def __load__(self, file: Path) -> dict[str, dict] | None:
        try:
            with open(file, "rb") as config_file:
                return yaml.safe_load(config_file)
        except FileNotFoundError as e:
            logging.warning(f"Missing {e.filename}.")
        return None

    def __merge_dict__(self, src: dict, dst: dict) -> None:
        for k, v in src.items():
            # key doesn't exist in destination or value isn't a dict, overwrite
            if not k in dst or not isinstance(v, dict):
                dst[k] = v
                continue

            # key exist in destination, and value is a dict. Recursively merge
            self.__merge_dict__(v, dst[k])

    def __merge_env__(self, prefix: str, dst: dict) -> None:
        for k, v in dst.items():
            key = f"{prefix}_{k}".upper()
            if isinstance(v, dict):
                self.__merge_env__(key, v)
            else:
                value = os.getenv(key)
                if value:
                    try:
                        dst[k] = ast.literal_eval(value)
                    except ValueError:
                        logging.warn(f"Treating '{value}' for {key} as string")
                        dst[k] = value

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
            self.__merge_dict__(config, ret)

        # overwrite with environment variables, if exist
        self.__merge_env__(self._prefix, ret)

        return ret
