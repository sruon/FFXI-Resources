from dataclasses import dataclass


@dataclass
class ParsedString:
    index: int
    offset: int
    text: str


@dataclass
class ParsedStringDat:
    entry_count: int
    strings: list[ParsedString]
