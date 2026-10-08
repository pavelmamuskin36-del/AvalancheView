from dataclasses import dataclass


@dataclass(frozen=True)
class VariableInfo:
    name: str
    dimensions: tuple[str, ...]
    shape: tuple[int, ...]
    units: str = ""
    description: str = ""
    derived: bool = False
    coordinate: bool = False
    plottable: bool = False
