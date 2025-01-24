import importlib
import sys
from dataclasses import dataclass
from typing import Any, List

from pkg_resources import iter_entry_points


@dataclass
class _EntryPoint:
    key: str
    module_name: str
    class_name: str

    def load(self) -> Any:
        module = importlib.import_module(self.module_name)
        return getattr(module, self.class_name)


def read_entry_points(group: str) -> List[_EntryPoint]:
    return [
        _EntryPoint(ep.name, ep.module_name, ep.attrs[0])
        for ep in iter_entry_points(group)
    ]
