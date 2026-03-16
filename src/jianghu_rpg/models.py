from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


STAT_NAMES = (
    "strength",
    "dexterity",
    "constitution",
    "insight",
    "spirit",
    "charisma",
)

EQUIPMENT_SLOTS = ("weapon", "armor", "accessory")


class WorldDocument(BaseModel):
    id: str
    title: str
    category: str
    text: str
    tags: list[str] = Field(default_factory=list)


class ItemDefinition(BaseModel):
    id: str
    name: str
    description: str
    category: Literal["weapon", "armor", "consumable", "material", "quest", "accessory"]
    slot: str | None = None
    stackable: bool = True
    max_stack: int = 99
    weight: float = 0.1
    value: int = 0
    stat_bonuses: dict[str, int] = Field(default_factory=dict)
    heal: int = 0
    qi_restore: int = 0
    tags: list[str] = Field(default_factory=list)


class InventoryEntry(BaseModel):
    item_id: str
    quantity: int = 1
    equipped: bool = False


class Requirement(BaseModel):
    flags_all: list[str] = Field(default_factory=list)
    flags_any: list[str] = Field(default_factory=list)
    flags_not: list[str] = Field(default_factory=list)
    min_reputation: dict[str, int] = Field(default_factory=dict)
    items: dict[str, int] = Field(default_factory=dict)
    min_silver: int = 0


class ChoiceEffect(BaseModel):
    xp: int = 0
    silver: int = 0
    hp: int = 0
    qi: int = 0
    add_items: dict[str, int] = Field(default_factory=dict)
    remove_items: dict[str, int] = Field(default_factory=dict)
    reputations: dict[str, int] = Field(default_factory=dict)
    set_flags: list[str] = Field(default_factory=list)
    clear_flags: list[str] = Field(default_factory=list)
    set_world_flags: list[str] = Field(default_factory=list)
    clear_world_flags: list[str] = Field(default_factory=list)
    faction_states: dict[str, str] = Field(default_factory=dict)
    location_states: dict[str, str] = Field(default_factory=dict)
    rumors: list[str] = Field(default_factory=list)
    allies: list[str] = Field(default_factory=list)
    chapter_shift: int = 0
    time_advance: int = 1
    unlock_talents: list[str] = Field(default_factory=list)


class Challenge(BaseModel):
    stat: str
    dc: int
    success_node: str
    failure_node: str


class Choice(BaseModel):
    id: str
    label: str
    description: str
    next_node: str | None = None
    requirements: Requirement = Field(default_factory=Requirement)
    challenge: Challenge | None = None
    effects: ChoiceEffect = Field(default_factory=ChoiceEffect)
    success_effects: ChoiceEffect = Field(default_factory=ChoiceEffect)
    failure_effects: ChoiceEffect = Field(default_factory=ChoiceEffect)
    success_text: str = ""
    failure_text: str = ""


class StoryNode(BaseModel):
    id: str
    chapter: str
    title: str
    location: str
    body: str
    tags: list[str] = Field(default_factory=list)
    choices: list[Choice] = Field(default_factory=list)
    auto_save: bool = True
    ending: bool = False


class Character(BaseModel):
    name: str
    gender: str
    origin: str
    tendency: str
    title: str = "江湖新客"
    level: int = 1
    xp: int = 0
    silver: int = 50
    hp: int = 18
    max_hp: int = 18
    qi: int = 12
    max_qi: int = 12
    attributes: dict[str, int] = Field(
        default_factory=lambda: {
            "strength": 10,
            "dexterity": 10,
            "constitution": 10,
            "insight": 10,
            "spirit": 10,
            "charisma": 10,
        }
    )
    reputations: dict[str, int] = Field(
        default_factory=lambda: {"沧浪盟": 0, "无相司": 0, "青灯寺": 0, "江湖声望": 0}
    )
    talents: list[str] = Field(default_factory=list)
    equipped: dict[str, str | None] = Field(
        default_factory=lambda: {"weapon": None, "armor": None, "accessory": None}
    )

    def modifier(self, stat: str, bonus: int = 0) -> int:
        score = self.attributes.get(stat, 10) + bonus
        return (score - 10) // 2

    def capacity(self) -> float:
        return 24.0 + max(0, self.modifier("strength")) * 8.0

    def xp_to_next_level(self) -> int:
        return 120 * self.level


class WorldState(BaseModel):
    current_node: str = "hanxi_ashes"
    chapter_index: int = 1
    day: int = 1
    location: str = "寒溪村"
    completed_nodes: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    world_flags: list[str] = Field(default_factory=list)
    faction_states: dict[str, str] = Field(
        default_factory=lambda: {"沧浪盟": "观望", "无相司": "搜捕", "青灯寺": "闭门"}
    )
    location_states: dict[str, str] = Field(
        default_factory=lambda: {"寒溪村": "焚毁", "青麓渡": "戒严", "龙渊地宫": "封闭"}
    )
    rumor_log: list[str] = Field(default_factory=list)
    event_log: list[str] = Field(default_factory=list)
    allies: list[str] = Field(default_factory=list)


class GameState(BaseModel):
    version: str = "0.1.0"
    save_slot: str = "autosave"
    character: Character
    inventory: list[InventoryEntry] = Field(default_factory=list)
    world: WorldState = Field(default_factory=WorldState)


class RollOutcome(BaseModel):
    stat: str
    dc: int
    roll: int
    modifier: int
    bonus: int
    total: int
    success: bool
    critical: str | None = None


class FreeActionPlan(BaseModel):
    narrative: str = ""
    next_node: str | None = None
    location: str | None = None
    effects: ChoiceEffect = Field(default_factory=ChoiceEffect)
