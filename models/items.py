from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Discriminator


class ItemName(BaseModel):
    english: str = ""
    english_log_single: str = ""
    english_log_plural: str = ""
    japanese: str = ""


class ItemDescription(BaseModel):
    english: str = ""
    japanese: str = ""


class ChargeData(BaseModel):
    max_charges: int
    cast_time: float
    cast_delay: int
    recast_delay: int


class WeaponData(BaseModel):
    level: int
    slots: list[str]
    races: list[str]
    jobs: list[str]
    damage: int | None = None
    delay: int | None = None
    dps: int | None = None
    skill: str | None = None
    jug_size: int | None = None
    emote: int | None = None
    item_level: int | None = None
    superior_level: int | None = None
    unknown1: int | None = None
    unknown2: int | None = None
    unknown3: int | None = None
    charges: ChargeData | None = None


class ArmorData(BaseModel):
    level: int
    slots: list[str]
    races: list[str]
    jobs: list[str]
    shield_size: int | None = None
    item_level: int | None = None
    superior_level: int | None = None
    unknown1: int | None = None
    unknown2: int | None = None
    unknown3: int | None = None
    charges: ChargeData | None = None


class UsableData(BaseModel):
    cast_time: float | None = None
    unknown1: int | None = None
    unknown2: int | None = None
    unknown3: int | None = None


class FurnishingData(BaseModel):
    element: str
    storage: int
    unknown3: int | None = None
    model_no: int | None = None
    size_x: int | None = None
    size_z: int | None = None
    height: int | None = None
    placement_flags: list[str] | None = None


class PuppetData(BaseModel):
    slot: int
    element_charge: int
    unknown1: int | None = None


class InstinctData(BaseModel):
    instinct_cost: int
    unknown1: int | None = None
    unknown2: int | None = None
    unknown3: int | None = None
    unknown4: int | None = None
    unknown5: int | None = None
    unknown6: int | None = None
    unknown7: int | None = None


class SlipData(BaseModel):
    unknown1: int | None = None
    unknowns: list[int] = []


class MonipulatorData(BaseModel):
    unknown1: int | None = None
    unknowns: list[int] = []


class _ItemBase(BaseModel):
    id: int
    resource_id: int
    name: ItemName
    description: ItemDescription
    type: str
    stack_size: int
    flags: list[str]
    targets: list[str]
    icon: str | None = None  # base64-encoded PNG


class WeaponItem(_ItemBase):
    category: Literal["weapon"]
    weapon: WeaponData


class ArmorItem(_ItemBase):
    category: Literal["armor"]
    armor: ArmorData


class UsableItem(_ItemBase):
    category: Literal["usable"]
    usable: UsableData


class FurnishingItem(_ItemBase):
    category: Literal["furnishing"]
    furnishing: FurnishingData


class PuppetItem(_ItemBase):
    category: Literal["puppet"]
    puppet: PuppetData


class InstinctItem(_ItemBase):
    category: Literal["instinct"]
    instinct: InstinctData


class SlipItem(_ItemBase):
    category: Literal["slip"]
    slip: SlipData


class MonipulatorItem(_ItemBase):
    category: Literal["monipulator"]
    monipulator: MonipulatorData


class GeneralItem(_ItemBase):
    category: Literal["general"]


AnyItem = Annotated[
    Union[
        WeaponItem,
        ArmorItem,
        UsableItem,
        FurnishingItem,
        PuppetItem,
        InstinctItem,
        SlipItem,
        MonipulatorItem,
        GeneralItem,
    ],
    Discriminator("category"),
]
