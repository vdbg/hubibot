import logging
from typing import Callable
import re


class Aliases:
    def __init__(self, conf, case_insensitive: bool):
        self._aliases: dict[str, list[list[str]]] = conf
        self._case_insensitive = case_insensitive

    def case_hack(self, name: str) -> str:
        # Gross Hack (tm) because Python doesn't support case comparers for dictionaries
        if self._case_insensitive:
            name = name.lower()
        return name

    def resolve(self, key: str, name: str, func: Callable[[str], any]) -> any:
        ret = func(self.case_hack(name))
        if ret:
            return ret

        if not self._aliases or not key in self._aliases:
            logging.warning(f"No aliases defined in config.yaml file section hubitat.aliases.{key}.")
            return None

        logging.debug(f"Searching for {key} called {name}.")
        regexes = self._aliases[key]

        for alias in regexes:
            pattern = self.case_hack(alias[0])
            sub = alias[1]
            new_name = re.sub(pattern, sub, name)
            logging.debug(f"Trying {key} alias regex s/{pattern}/{sub}/ => {new_name}")
            ret = func(self.case_hack(new_name))
            if ret:
                return ret

        logging.debug(f"{key} '{name}' was not found.")
        return None
