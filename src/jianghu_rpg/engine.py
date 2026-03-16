from __future__ import annotations

import json
import re
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from jianghu_rpg.config import CHROMA_DIR, OUTPUT_STYLE_REGEX, SAVE_DIR, STORY_DIR, WORLD_DIR
from jianghu_rpg.dice import resolve_check
from jianghu_rpg.longcat_client import LongCatNarrator
from jianghu_rpg.models import (
    EQUIPMENT_SLOTS,
    STAT_NAMES,
    Character,
    Choice,
    ChoiceEffect,
    FreeActionPlan,
    GameState,
    InventoryEntry,
    ItemDefinition,
    Requirement,
    RollOutcome,
    StoryNode,
)
from jianghu_rpg.output_formatter import OutputFormatter
from jianghu_rpg.vector_store import LoreVectorStore
from jianghu_rpg.world import WorldRepository


ORIGIN_PRESETS = {
    "寒溪村遗孤": {
        "mods": {"dexterity": 2, "insight": 1, "constitution": 1},
        "items": {"cloth_armor": 1, "healing_pill": 2, "burnt_jade": 1},
        "title": "残村孤影",
    },
    "云剑门弃徒": {
        "mods": {"strength": 2, "constitution": 1, "dexterity": 1},
        "items": {"iron_sword": 1, "cloth_armor": 1, "healing_pill": 1},
        "title": "旧门残剑",
    },
    "青灯寺俗家弟子": {
        "mods": {"spirit": 2, "insight": 1, "charisma": 1},
        "items": {"ash_beads": 1, "healing_pill": 2, "smoke_pellet": 1},
        "title": "灯下行人",
    },
}

TENDENCY_PRESETS = {
    "侠义": {"reputation": {"江湖声望": 4, "青灯寺": 1}, "talent": "济弱扶倾"},
    "权谋": {"reputation": {"无相司": 3}, "talent": "借势藏锋"},
    "求道": {"reputation": {"青灯寺": 3}, "talent": "坐照观心"},
}

TALENT_BONUSES = {
    "济弱扶倾": {"charisma": 1, "spirit": 1},
    "借势藏锋": {"insight": 1, "charisma": 1},
    "坐照观心": {"insight": 1, "spirit": 2},
    "龙吟诀": {"strength": 1, "spirit": 1},
    "照影步": {"dexterity": 2},
    "破妄心印": {"insight": 2},
}


class GameEngine:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self.repo = WorldRepository(WORLD_DIR, STORY_DIR)
        self.store = LoreVectorStore(CHROMA_DIR)
        self.narrator = LongCatNarrator()
        self.output_formatter = OutputFormatter(OUTPUT_STYLE_REGEX)
        SAVE_DIR.mkdir(parents=True, exist_ok=True)

    def init_world(self) -> int:
        docs = self.repo.world_docs
        self.store.ingest(docs)
        return len(docs)

    def create_demo_state(self, slot: str = "demo_hero") -> GameState:
        character = Character(
            name="沈孤舟",
            gender="不详",
            origin="寒溪村遗孤",
            tendency="侠义",
            title="残村孤影",
        )
        self._apply_origin(character, "寒溪村遗孤")
        self._apply_tendency(character, "侠义")
        state = GameState(character=character, save_slot=slot)
        state.inventory = []
        for item_id, amount in ORIGIN_PRESETS["寒溪村遗孤"]["items"].items():
            self.add_item(state, item_id, amount)
        self._recalculate_resources(state)
        return state

    def create_character_interactive(self, slot: str = "autosave") -> GameState:
        self.console.print(Panel.fit("创建你的江湖角色", border_style="cyan"))
        name = Prompt.ask("角色名", default="沈孤舟")
        gender = Prompt.ask("称谓/性别描述", default="少侠")
        origin = self._choose_from_map("选择出身", ORIGIN_PRESETS)
        tendency = self._choose_from_map("选择取向", TENDENCY_PRESETS)

        character = Character(
            name=name,
            gender=gender,
            origin=origin,
            tendency=tendency,
            title=ORIGIN_PRESETS[origin]["title"],
        )
        self._apply_origin(character, origin)
        self._apply_tendency(character, tendency)
        self._allocate_attributes(character)

        state = GameState(character=character, save_slot=slot)
        for item_id, amount in ORIGIN_PRESETS[origin]["items"].items():
            self.add_item(state, item_id, amount)
        self._recalculate_resources(state)
        return state

    def save_game(self, state: GameState, slot: str | None = None) -> Path:
        save_slot = slot or state.save_slot
        state.save_slot = save_slot
        save_path = SAVE_DIR / f"{save_slot}.json"
        save_path.write_text(
            json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return save_path

    def load_game(self, slot: str) -> GameState:
        save_path = SAVE_DIR / f"{slot}.json"
        payload = json.loads(save_path.read_text(encoding="utf-8"))
        return GameState.model_validate(payload)

    def list_saves(self) -> list[str]:
        return sorted(path.stem for path in SAVE_DIR.glob("*.json"))

    def run(self, state: GameState) -> None:
        self.init_world()
        greeting = (
            f"{state.character.name}踏入江湖。输入数字选择剧情，也可以直接用自然语言描述行动。"
            "查询信息建议用 `/背包`、`/状态`。输入 `h` 查看全部命令。"
        )
        self.console.print(Panel.fit(greeting, border_style="green"))
        last_choice: Choice | None = None
        last_roll: RollOutcome | None = None
        running = True
        while running:
            node = self.current_node(state)
            if node.id not in state.world.completed_nodes:
                state.world.completed_nodes.append(node.id)
            self._show_scene(state, node, last_choice=last_choice, last_roll=last_roll)
            if node.auto_save:
                self.save_game(state)
            if node.ending:
                self.console.print(Panel.fit("江湖篇章暂告一段落，已自动存档。", border_style="magenta"))
                break

            while True:
                choices = self.available_choices(state, node)
                if not choices:
                    self.console.print("当前场景没有可执行选项，已自动保存并返回。", style="yellow")
                    self.save_game(state)
                    running = False
                    break
                self._print_choices(choices)
                command = Prompt.ask("你的行动", default="1").strip()

                state, status, refresh_scene = self._handle_system_command(state, node, command)
                if status == "quit":
                    running = False
                    break
                if status == "handled":
                    last_choice = None
                    last_roll = None
                    if refresh_scene:
                        break
                    continue

                try:
                    index = int(command) - 1
                except ValueError:
                    handled_free_action, refresh_scene = self._handle_free_action(state, node, command)
                    if handled_free_action:
                        last_choice = None
                        last_roll = None
                        if refresh_scene:
                            break
                        continue
                    self.console.print("无法识别该输入。可输入 `h` 查看命令，或直接描述具体行动。", style="red")
                    continue
                if index < 0 or index >= len(choices):
                    self.console.print("选项超出范围。", style="red")
                    continue
                selected = choices[index]
                last_choice, last_roll = self.resolve_choice(state, node, selected)
                break

    def _handle_system_command(
        self,
        state: GameState,
        node: StoryNode,
        command: str,
    ) -> tuple[GameState, str, bool]:
        intent, argument = self._parse_natural_command(command)
        if intent is None:
            return state, "unhandled", False

        if intent == "help":
            self._print_help()
            return state, "handled", False
        if intent == "inventory":
            self._show_inventory(state)
            return state, "handled", False
        if intent == "status":
            self._show_status(state)
            return state, "handled", False
        if intent == "save":
            slot = argument or Prompt.ask("存档名", default=state.save_slot)
            path = self.save_game(state, slot)
            self.console.print(f"已保存到 {path}")
            return state, "handled", False
        if intent == "load":
            slot = argument or Prompt.ask("要读取的存档名")
            try:
                loaded = self.load_game(slot)
            except FileNotFoundError:
                self.console.print(f"未找到存档：{slot}", style="red")
                return state, "handled", False
            self.console.print(f"已切换到存档：{slot}", style="green")
            return loaded, "handled", True
        if intent == "saves":
            saves = self.list_saves()
            if not saves:
                self.console.print("当前没有存档。", style="yellow")
            else:
                self.console.print("可用存档：")
                for save in saves:
                    self.console.print(f"- {save}")
            return state, "handled", False
        if intent == "equip":
            target = argument or Prompt.ask("输入要装备的物品名称或ID")
            self.equip_item(state, target)
            return state, "handled", False
        if intent == "use":
            target = argument or Prompt.ask("输入要使用的物品名称或ID")
            self.use_item(state, target)
            return state, "handled", False
        if intent == "lore":
            query = argument or Prompt.ask("想追问的江湖关键词", default=node.location)
            self._show_lore(query)
            return state, "handled", False
        if intent == "new":
            slot = argument or Prompt.ask("新角色存档名", default="autosave")
            new_state = self.create_character_interactive(slot=slot)
            self.save_game(new_state, slot)
            self.console.print(f"新角色已创建并存入 {slot}。", style="green")
            return new_state, "handled", True
        if intent == "menu":
            return self._open_session_menu(state)
        if intent == "quit":
            path = self.save_game(state)
            self.console.print(f"进度已保存到 {path}")
            return state, "quit", False
        return state, "unhandled", False

    def _parse_natural_command(self, command: str) -> tuple[str | None, str | None]:
        text = command.strip()
        if not text:
            return None, None
        lowered = text.lower()
        if re.fullmatch(r"\d+", text):
            return None, None

        prefixed = self._parse_prefixed_command(text)
        if prefixed[0] is not None:
            return prefixed

        if lowered in {"h", "help"} or text in {"帮助", "命令", "查看命令"}:
            return "help", None
        if lowered in {"i", "inventory"} or text in {"背包", "查看背包", "打开背包", "查看物品", "物品栏"}:
            return "inventory", None
        if self._looks_like_inventory_query(text):
            return "inventory", None
        if lowered in {"s", "status"} or text in {"状态", "查看状态", "角色状态", "角色信息", "人物状态", "属性面板"}:
            return "status", None
        if self._looks_like_status_query(text):
            return "status", None
        if lowered in {"q", "quit", "exit"} or text in {"退出游戏", "结束游戏", "离开江湖"}:
            return "quit", None
        if lowered == "menu" or text in {"返回菜单", "主菜单", "回到菜单"}:
            return "menu", None
        if text in {"存档列表", "查看存档", "有哪些存档", "列出存档"}:
            return "saves", None

        load_match = re.search(r"(?:加载|读取|切换|换到)(?:存档)?\s*(?:到|为|:|：)?\s*([^\s]+)", text)
        if load_match:
            return "load", load_match.group(1).strip()
        if "读取存档" in text or "加载存档" in text or "切换存档" in text:
            return "load", None

        save_match = re.search(r"(?:保存|存档|另存为|另存)\s*(?:到|为|:|：)?\s*([^\s]+)", text)
        if save_match:
            slot = save_match.group(1).strip()
            if slot not in {"一个", "当前", "进度"}:
                return "save", slot
        if lowered in {"v", "save"} or text in {"保存", "存档", "快速保存"}:
            return "save", None

        new_match = re.search(r"(?:新建角色|创建角色|重开新档|重新开始)\s*(?:为|:|：)?\s*([^\s]+)?", text)
        if new_match and new_match.group(0).strip():
            arg = (new_match.group(1) or "").strip() or None
            return "new", arg

        lore_match = re.search(r"(?:查询|打听|追问|了解)\s*(?:关于|一下|:|：)?\s*(.+)", text)
        if lowered in {"l", "lore"}:
            return "lore", None
        if lore_match:
            return "lore", lore_match.group(1).strip()

        equip_match = re.search(r"(?:装备|佩戴|穿上|换上)\s*(.+)", text)
        if lowered in {"e", "equip"}:
            return "equip", None
        if equip_match:
            return "equip", equip_match.group(1).strip()

        use_match = re.search(r"(?:使用|服用|吃下|吞下)\s*(.+)", text)
        if lowered in {"u", "use"}:
            return "use", None
        if use_match:
            return "use", use_match.group(1).strip()

        return None, None

    def _parse_prefixed_command(self, text: str) -> tuple[str | None, str | None]:
        if not text.startswith(("/", ":")):
            return None, None
        payload = text[1:].strip()
        if not payload:
            return "help", None
        parts = payload.split(maxsplit=1)
        head = parts[0].lower()
        tail = parts[1].strip() if len(parts) > 1 else None

        if head in {"h", "help", "帮助"}:
            return "help", None
        if head in {"i", "inventory", "bag", "背包"}:
            return "inventory", None
        if head in {"s", "status", "char", "角色", "状态"}:
            return "status", None
        if head in {"v", "save", "存档", "保存"}:
            return "save", tail
        if head in {"load", "读取", "加载", "切档", "切换存档"}:
            return "load", tail
        if head in {"saves", "存档列表", "list"}:
            return "saves", None
        if head in {"l", "lore", "资料", "世界"}:
            return "lore", tail
        if head in {"e", "equip", "装备"}:
            return "equip", tail
        if head in {"u", "use", "使用"}:
            return "use", tail
        if head in {"new", "新建角色", "创建角色"}:
            return "new", tail
        if head in {"menu", "菜单"}:
            return "menu", None
        if head in {"q", "quit", "exit", "退出"}:
            return "quit", None
        return None, None

    def _looks_like_inventory_query(self, text: str) -> bool:
        lowered = text.lower()
        inventory_words = ("背包", "包里", "物品", "道具", "inventory", "bag", "items")
        if not any(token in text for token in inventory_words) and not any(token in lowered for token in inventory_words):
            return False
        if self._contains_story_action_marker(text):
            return False
        if re.search(r"(查看|看看|查询|显示|告诉我|给我看|我想看|我想知道).*(背包|包里|物品|道具)", text):
            return True
        if re.search(r"(背包|包里|物品|道具).*(有什么|有啥|哪些|清单|还剩|多少)", text):
            return True
        if re.search(r"(show|check|what.*(inventory|bag|items))", lowered):
            return True
        if ("?" in text or "？" in text or "吗" in text) and ("背包" in text or "包里" in text or "inventory" in lowered):
            return True
        return False

    def _looks_like_status_query(self, text: str) -> bool:
        lowered = text.lower()
        status_words = ("状态", "属性", "面板", "血量", "真气", "等级", "声望", "status", "hp", "qi", "level")
        if not any(token in text for token in status_words) and not any(token in lowered for token in status_words):
            return False
        if self._contains_story_action_marker(text):
            return False
        if re.search(r"(查看|看看|查询|显示|告诉我|给我看|我想看|我想知道).*(状态|属性|面板|血量|真气|等级|声望)", text):
            return True
        if re.search(r"(状态|属性|面板|血量|真气|等级|声望).*(多少|如何|怎么样|还剩|咋样|\?|？)", text):
            return True
        if re.search(r"(show|check).*(status|hp|qi|level)", lowered):
            return True
        if re.search(r"(how much|what).*(hp|qi|level|status)", lowered):
            return True
        if any(token in lowered for token in ("hp", "qi", "level", "status")) and any(
            token in text for token in ("?", "？", "吗", "多少", "几", "咋样")
        ):
            return True
        return False

    @staticmethod
    def _contains_story_action_marker(text: str) -> bool:
        markers = (
            "然后",
            "接着",
            "之后",
            "并且",
            "潜入",
            "潜行",
            "攻击",
            "追击",
            "追杀",
            "偷袭",
            "伪装",
            "翻墙",
            "闯入",
            "谈判",
            "试探",
            "埋伏",
            "撤离",
            "前往",
            "行动",
            "sneak",
            "attack",
            "chase",
            "hide",
            "ambush",
            "negotiate",
        )
        lowered = text.lower()
        return any(token in text for token in markers) or any(token in lowered for token in markers)

    def _open_session_menu(self, state: GameState) -> tuple[GameState, str, bool]:
        menu_text = (
            "1. 继续当前剧情\n"
            "2. 保存当前进度\n"
            "3. 切换存档\n"
            "4. 查看存档列表\n"
            "5. 创建并切换到新角色\n"
            "6. 结束游戏"
        )
        self.console.print(Panel.fit(menu_text, title="主菜单", border_style="white"))
        selection = Prompt.ask(
            "菜单操作",
            choices=["1", "2", "3", "4", "5", "6"],
            default="1",
        )
        if selection == "1":
            return state, "handled", False
        if selection == "2":
            slot = Prompt.ask("存档名", default=state.save_slot)
            path = self.save_game(state, slot)
            self.console.print(f"已保存到 {path}")
            return state, "handled", False
        if selection == "3":
            slot = Prompt.ask("要读取的存档名")
            try:
                loaded = self.load_game(slot)
            except FileNotFoundError:
                self.console.print(f"未找到存档：{slot}", style="red")
                return state, "handled", False
            self.console.print(f"已切换到存档：{slot}", style="green")
            return loaded, "handled", True
        if selection == "4":
            saves = self.list_saves()
            if not saves:
                self.console.print("当前没有存档。", style="yellow")
            else:
                self.console.print("可用存档：")
                for save in saves:
                    self.console.print(f"- {save}")
            return state, "handled", False
        if selection == "5":
            slot = Prompt.ask("新角色存档名", default="autosave")
            new_state = self.create_character_interactive(slot=slot)
            self.save_game(new_state, slot)
            self.console.print(f"新角色已创建并存入 {slot}。", style="green")
            return new_state, "handled", True
        path = self.save_game(state)
        self.console.print(f"进度已保存到 {path}")
        return state, "quit", False

    def _handle_free_action(self, state: GameState, node: StoryNode, action_text: str) -> tuple[bool, bool]:
        action_text = action_text.strip()
        if not action_text:
            return False, False
        if action_text.startswith(("/", ":")):
            return False, False
        if len(action_text) < 2:
            return False, False
        if not self.narrator.enabled:
            self.console.print("自由行动需要启用 LongCat（请配置 LONGCAT_API_KEY）。", style="yellow")
            return False, False

        lore_context = self.store.search(f"{self._build_lore_query(state, node)} {action_text}", limit=4)
        candidate_nodes = self.repo.candidate_nodes_near(
            start_node_id=state.world.current_node,
            depth=2,
            limit=24,
        )
        plan = self.narrator.plan_free_action(
            state=state,
            node=node,
            action_text=action_text,
            lore_context=lore_context,
            candidate_nodes=candidate_nodes,
            known_item_ids=sorted(self.repo.items.keys()),
            factions=sorted(state.character.reputations.keys()),
        )
        if plan is None:
            return False, False

        plan = self._sanitize_free_action_plan(state, plan)
        before_node = state.world.current_node
        before_location = state.world.location
        before_day = state.world.day

        self.apply_effects(state, plan.effects)
        if plan.location:
            state.world.location = plan.location
        if plan.next_node:
            if self.repo.has_story_node(plan.next_node):
                next_node = self.repo.get_story_node(plan.next_node)
                state.world.current_node = next_node.id
                state.world.location = next_node.location
            else:
                self.console.print(f"导演建议跳转到未知节点 `{plan.next_node}`，已保持当前主线。", style="yellow")

        narrative = plan.narrative or "你以自己的方式出手，江湖走向悄然改变。"
        rendered_narrative = self.output_formatter.format_narrative(narrative)
        self.console.print(Panel(rendered_narrative, title="自由行动裁定", border_style="cyan"))
        self._check_level_up(state)
        self.save_game(state)
        refresh_scene = (
            state.world.current_node != before_node
            or state.world.location != before_location
            or state.world.day != before_day
        )
        return True, refresh_scene

    def _sanitize_free_action_plan(self, state: GameState, plan: FreeActionPlan) -> FreeActionPlan:
        clean = plan.model_copy(deep=True)
        effects = clean.effects
        effects.xp = max(-10, min(40, effects.xp))
        effects.silver = max(-50, min(50, effects.silver))
        effects.hp = max(-8, min(8, effects.hp))
        effects.qi = max(-8, min(8, effects.qi))
        effects.chapter_shift = max(-1, min(1, effects.chapter_shift))
        effects.time_advance = max(0, min(3, effects.time_advance))

        effects.add_items = {
            item_id: max(1, min(5, amount))
            for item_id, amount in effects.add_items.items()
            if item_id in self.repo.items and amount > 0
        }
        effects.remove_items = {
            item_id: max(1, min(5, amount))
            for item_id, amount in effects.remove_items.items()
            if item_id in self.repo.items and amount > 0
        }
        known_factions = set(state.character.reputations.keys())
        effects.reputations = {
            faction: max(-3, min(3, value))
            for faction, value in effects.reputations.items()
            if faction in known_factions
        }
        effects.set_flags = effects.set_flags[:4]
        effects.clear_flags = effects.clear_flags[:4]
        effects.set_world_flags = effects.set_world_flags[:4]
        effects.clear_world_flags = effects.clear_world_flags[:4]
        effects.rumors = effects.rumors[:3]
        effects.allies = effects.allies[:2]
        effects.unlock_talents = [name for name in effects.unlock_talents if name in TALENT_BONUSES][:2]

        if clean.next_node and not self.repo.has_story_node(clean.next_node):
            clean.next_node = None
        if clean.location:
            clean.location = clean.location.strip()[:24]
        clean.narrative = clean.narrative.strip()[:320]
        return clean

    def current_node(self, state: GameState) -> StoryNode:
        return self.repo.get_story_node(state.world.current_node)

    def available_choices(self, state: GameState, node: StoryNode) -> list[Choice]:
        return [choice for choice in node.choices if self.requirements_met(state, choice.requirements)]

    def requirements_met(self, state: GameState, requirements: Requirement) -> bool:
        flag_set = set(state.world.flags)
        if requirements.flags_all and not set(requirements.flags_all).issubset(flag_set):
            return False
        if requirements.flags_any and not flag_set.intersection(requirements.flags_any):
            return False
        if requirements.flags_not and flag_set.intersection(requirements.flags_not):
            return False
        for faction, threshold in requirements.min_reputation.items():
            if state.character.reputations.get(faction, 0) < threshold:
                return False
        if state.character.silver < requirements.min_silver:
            return False
        for item_id, count in requirements.items.items():
            if self.count_item(state, item_id) < count:
                return False
        return True

    def resolve_choice(self, state: GameState, node: StoryNode, choice: Choice) -> tuple[Choice, RollOutcome | None]:
        self.apply_effects(state, choice.effects)
        outcome = None
        next_node = choice.next_node
        if choice.challenge is not None:
            bonus = self.stat_bonus_from_gear(state, choice.challenge.stat) + self.stat_bonus_from_talents(
                state, choice.challenge.stat
            )
            modifier = state.character.modifier(choice.challenge.stat)
            outcome = resolve_check(choice.challenge.stat, choice.challenge.dc, modifier, bonus)
            message = choice.success_text if outcome.success else choice.failure_text
            if message:
                self.console.print(Panel.fit(message, border_style="yellow"))
            if outcome.success:
                self.apply_effects(state, choice.success_effects)
                next_node = choice.challenge.success_node
            else:
                self.apply_effects(state, choice.failure_effects)
                next_node = choice.challenge.failure_node
            self.console.print(
                f"检定结果: d20={outcome.roll}，修正={outcome.modifier}，加值={outcome.bonus}，总计={outcome.total}，"
                f"对抗难度 {outcome.dc}。"
            )
        next_story_node = self.repo.get_story_node(next_node) if next_node else node
        lore_context = self.store.search(f"{node.location} {choice.label} {next_story_node.location}", limit=3)
        resolution_text = self.narrator.describe_resolution(
            state,
            node,
            next_story_node,
            choice,
            lore_context,
            outcome=outcome,
        )
        if resolution_text:
            rendered_resolution = self.output_formatter.format_narrative(resolution_text)
            self.console.print(Panel(rendered_resolution, title="江湖余波", border_style="magenta"))
        state.world.location = next_story_node.location
        if next_node:
            state.world.current_node = next_node
        self._recalculate_resources(state)
        self._check_level_up(state)
        return choice, outcome

    def apply_effects(self, state: GameState, effects: ChoiceEffect) -> None:
        character = state.character
        character.xp += effects.xp
        character.silver = max(0, character.silver + effects.silver)
        character.hp += effects.hp
        character.qi += effects.qi
        for item_id, amount in effects.add_items.items():
            self.add_item(state, item_id, amount)
        for item_id, amount in effects.remove_items.items():
            self.remove_item(state, item_id, amount)
        for faction, value in effects.reputations.items():
            character.reputations[faction] = character.reputations.get(faction, 0) + value
        for flag in effects.set_flags:
            if flag not in state.world.flags:
                state.world.flags.append(flag)
        for flag in effects.clear_flags:
            if flag in state.world.flags:
                state.world.flags.remove(flag)
        for flag in effects.set_world_flags:
            if flag not in state.world.world_flags:
                state.world.world_flags.append(flag)
        for flag in effects.clear_world_flags:
            if flag in state.world.world_flags:
                state.world.world_flags.remove(flag)
        state.world.faction_states.update(effects.faction_states)
        state.world.location_states.update(effects.location_states)
        for rumor in effects.rumors:
            if rumor not in state.world.rumor_log:
                state.world.rumor_log.append(rumor)
        for ally in effects.allies:
            if ally not in state.world.allies:
                state.world.allies.append(ally)
        for talent in effects.unlock_talents:
            if talent not in character.talents:
                character.talents.append(talent)
        state.world.chapter_index += effects.chapter_shift
        state.world.day += max(0, effects.time_advance)
        state.world.event_log.append(self._effect_log_text(effects))
        self._recalculate_resources(state)

    def add_item(self, state: GameState, item_id: str, quantity: int = 1) -> None:
        item = self.repo.items[item_id]
        if item.stackable:
            existing = next((entry for entry in state.inventory if entry.item_id == item_id and not entry.equipped), None)
            if existing:
                existing.quantity += quantity
            else:
                state.inventory.append(InventoryEntry(item_id=item_id, quantity=quantity))
            return
        for _ in range(quantity):
            state.inventory.append(InventoryEntry(item_id=item_id, quantity=1))

    def remove_item(self, state: GameState, item_id: str, quantity: int = 1) -> bool:
        target = quantity
        for entry in list(state.inventory):
            if entry.item_id != item_id:
                continue
            if self.repo.items[item_id].stackable:
                if entry.quantity >= target:
                    entry.quantity -= target
                    if entry.quantity <= 0:
                        state.inventory.remove(entry)
                    return True
                target -= entry.quantity
                state.inventory.remove(entry)
            else:
                if entry.equipped:
                    continue
                state.inventory.remove(entry)
                target -= 1
                if target <= 0:
                    return True
        return target <= 0

    def count_item(self, state: GameState, item_id: str) -> int:
        return sum(entry.quantity for entry in state.inventory if entry.item_id == item_id)

    def equip_item(self, state: GameState, query: str) -> None:
        entry = self._find_inventory_entry(state, query)
        if entry is None:
            self.console.print("没有找到该物品。", style="red")
            return
        item = self.repo.items[entry.item_id]
        if item.slot not in EQUIPMENT_SLOTS:
            self.console.print("这个物品无法装备。", style="red")
            return
        current_item_id = state.character.equipped.get(item.slot)
        if current_item_id:
            for candidate in state.inventory:
                if candidate.item_id == current_item_id and candidate.equipped:
                    candidate.equipped = False
                    break
        entry.equipped = True
        state.character.equipped[item.slot] = item.id
        self.console.print(f"已装备 {item.name}。", style="green")

    def use_item(self, state: GameState, query: str) -> None:
        entry = self._find_inventory_entry(state, query)
        if entry is None:
            self.console.print("没有找到该物品。", style="red")
            return
        item = self.repo.items[entry.item_id]
        if item.category != "consumable":
            self.console.print("该物品不可直接使用。", style="red")
            return
        state.character.hp = min(state.character.max_hp, state.character.hp + item.heal)
        state.character.qi = min(state.character.max_qi, state.character.qi + item.qi_restore)
        self.remove_item(state, item.id, 1)
        self.console.print(f"你使用了 {item.name}。", style="green")

    def stat_bonus_from_gear(self, state: GameState, stat: str) -> int:
        bonus = 0
        for item_id in state.character.equipped.values():
            if not item_id:
                continue
            bonus += self.repo.items[item_id].stat_bonuses.get(stat, 0)
        return bonus

    def stat_bonus_from_talents(self, state: GameState, stat: str) -> int:
        bonus = 0
        for talent in state.character.talents:
            bonus += TALENT_BONUSES.get(talent, {}).get(stat, 0)
        return bonus

    def total_inventory_weight(self, state: GameState) -> float:
        total = 0.0
        for entry in state.inventory:
            item = self.repo.items[entry.item_id]
            total += item.weight * entry.quantity
        return total

    def _show_scene(
        self,
        state: GameState,
        node: StoryNode,
        last_choice: Choice | None = None,
        last_roll: RollOutcome | None = None,
    ) -> None:
        lore_context = self.store.search(self._build_lore_query(state, node))
        generated = self.narrator.describe_scene(
            state,
            node,
            lore_context,
            last_result=last_roll,
            last_choice=last_choice,
        )
        scene_text = generated or self._fallback_scene_text(state, node, lore_context, last_roll)
        subtitle = f"{node.chapter} | 地点：{node.location} | 第 {state.world.day} 日"
        rendered_text = self.output_formatter.format_narrative(scene_text)
        self.console.print(Panel(rendered_text, title=node.title, subtitle=subtitle, border_style="blue"))

    def _fallback_scene_text(
        self,
        state: GameState,
        node: StoryNode,
        lore_context: list[dict[str, str]],
        last_roll: RollOutcome | None,
    ) -> str:
        lore_lines = []
        for entry in lore_context[:2]:
            lore_lines.append(f"{entry['title']}：{entry['text'][:70]}...")
        roll_text = ""
        if last_roll is not None:
            outcome = "成" if last_roll.success else "败"
            roll_text = (
                f"\n上一回合检定以 {outcome} 收束，"
                f"你记得那一掷 {last_roll.roll} 点的寒意仍停在指骨里。"
            )
        world_text = (
            f"当下江湖传闻：{ '；'.join(state.world.rumor_log[-2:]) if state.world.rumor_log else '风声尚未完全外泄。'}"
        )
        lore_text = "\n".join(lore_lines) if lore_lines else "你只能依靠手中线索，继续向更深的黑暗处行去。"
        return f"{node.body}{roll_text}\n\n{world_text}\n{lore_text}"

    def _build_lore_query(self, state: GameState, node: StoryNode) -> str:
        return " ".join(
            [
                node.location,
                node.title,
                *node.tags,
                *state.world.flags[-4:],
                *state.world.world_flags[-2:],
            ]
        )

    def _print_choices(self, choices: list[Choice]) -> None:
        table = Table(title="可选行动", show_lines=False)
        table.add_column("#", style="cyan", width=4)
        table.add_column("行动")
        table.add_column("说明")
        for index, choice in enumerate(choices, start=1):
            detail = choice.description
            if choice.challenge is not None:
                detail = f"{detail} [检定 {choice.challenge.stat} / DC {choice.challenge.dc}]"
            table.add_row(str(index), choice.label, detail)
        self.console.print(table)

    def _show_status(self, state: GameState) -> None:
        char = state.character
        table = Table(title=f"{char.name} 的状态")
        table.add_column("项目")
        table.add_column("数值")
        table.add_row("身份", f"{char.title} / {char.origin} / {char.tendency}")
        table.add_row("等级", f"{char.level} (XP {char.xp}/{char.xp_to_next_level()})")
        table.add_row("生命", f"{char.hp}/{char.max_hp}")
        table.add_row("真气", f"{char.qi}/{char.max_qi}")
        table.add_row("银钱", str(char.silver))
        for stat in STAT_NAMES:
            gear = self.stat_bonus_from_gear(state, stat)
            talent = self.stat_bonus_from_talents(state, stat)
            table.add_row(stat, f"{char.attributes[stat]} (装备+{gear} / 天赋+{talent})")
        table.add_row("同盟", "、".join(state.world.allies) if state.world.allies else "暂无")
        self.console.print(table)

    def _show_inventory(self, state: GameState) -> None:
        table = Table(title="背包")
        table.add_column("物品")
        table.add_column("数量")
        table.add_column("类型")
        table.add_column("状态")
        table.add_column("说明")
        for entry in state.inventory:
            item = self.repo.items[entry.item_id]
            status = "已装备" if entry.equipped else "-"
            table.add_row(item.name, str(entry.quantity), item.category, status, item.description)
        table.caption = f"负重 {self.total_inventory_weight(state):.1f}/{state.character.capacity():.1f}"
        self.console.print(table)

    def _show_lore(self, query: str) -> None:
        results = self.store.search(query, limit=3)
        if not results:
            self.console.print("未检索到相关江湖资料。", style="yellow")
            return
        for result in results:
            rendered = self.output_formatter.format_narrative(result["text"])
            self.console.print(Panel(rendered, title=result["title"], subtitle=result["category"], border_style="white"))

    def _print_help(self) -> None:
        self.console.print(
            Panel.fit(
                (
                    "数字: 推进剧情 | 自然语言: 例如“潜入后院偷听”“保存到 night1”“切换存档 demo_hero”\n"
                    "推荐指令前缀: /背包 /状态 /save slot /load slot /menu /quit（避免和剧情描述混淆）\n"
                    "i: 背包 | s: 状态 | e: 装备 | u: 使用物品 | l: 查询 lore | v: 存档 | menu: 主菜单 | q: 退出"
                ),
                border_style="white",
            )
        )

    def _choose_from_map(self, title: str, options: dict[str, dict]) -> str:
        self.console.print(Panel.fit(title, border_style="white"))
        keys = list(options.keys())
        for idx, key in enumerate(keys, start=1):
            self.console.print(f"{idx}. {key}")
        selection = Prompt.ask("输入编号", choices=[str(i) for i in range(1, len(keys) + 1)], default="1")
        return keys[int(selection) - 1]

    def _allocate_attributes(self, character: Character) -> None:
        points = 8
        self.console.print("你有 8 点可自由分配属性，每项最多加到 16。")
        while points > 0:
            summary = ", ".join(f"{stat}:{character.attributes[stat]}" for stat in STAT_NAMES)
            self.console.print(f"当前属性: {summary} | 剩余点数: {points}")
            stat = Prompt.ask("要提升的属性", choices=list(STAT_NAMES), default="insight")
            if character.attributes[stat] >= 16:
                self.console.print("该属性已达到本阶段上限。", style="yellow")
                continue
            character.attributes[stat] += 1
            points -= 1

    def _apply_origin(self, character: Character, origin: str) -> None:
        preset = ORIGIN_PRESETS[origin]
        for stat, amount in preset["mods"].items():
            character.attributes[stat] += amount
        character.title = preset["title"]

    def _apply_tendency(self, character: Character, tendency: str) -> None:
        preset = TENDENCY_PRESETS[tendency]
        for faction, amount in preset["reputation"].items():
            character.reputations[faction] = character.reputations.get(faction, 0) + amount
        if preset["talent"] not in character.talents:
            character.talents.append(preset["talent"])

    def _recalculate_resources(self, state: GameState) -> None:
        character = state.character
        character.max_hp = 12 + character.level * 4 + character.attributes["constitution"]
        character.max_qi = 8 + character.level * 3 + character.attributes["spirit"]
        character.hp = min(character.hp, character.max_hp)
        character.qi = min(character.qi, character.max_qi)

    def _check_level_up(self, state: GameState) -> None:
        character = state.character
        leveled = False
        while character.xp >= character.xp_to_next_level():
            character.xp -= character.xp_to_next_level()
            character.level += 1
            character.attributes["constitution"] += 1
            leveled = True
            self.console.print(Panel.fit(f"{character.name} 提升到了 {character.level} 级。", border_style="green"))
            stat = Prompt.ask("升级加点属性", choices=list(STAT_NAMES), default="spirit")
            character.attributes[stat] += 1
        if leveled:
            if character.level >= 3 and "照影步" not in character.talents:
                character.talents.append("照影步")
            if character.level >= 4 and "破妄心印" not in character.talents:
                character.talents.append("破妄心印")
            self._recalculate_resources(state)
            character.hp = character.max_hp
            character.qi = character.max_qi

    def _find_inventory_entry(self, state: GameState, query: str) -> InventoryEntry | None:
        lowered = query.strip().lower()
        for entry in state.inventory:
            item = self.repo.items[entry.item_id]
            if item.id.lower() == lowered or item.name.lower() == lowered or lowered in item.name.lower():
                return entry
        return None

    def _effect_log_text(self, effects: ChoiceEffect) -> str:
        parts: list[str] = []
        if effects.xp:
            parts.append(f"修为+{effects.xp}")
        if effects.silver:
            parts.append(f"银钱{effects.silver:+d}")
        if effects.reputations:
            rep_text = "，".join(f"{name}{value:+d}" for name, value in effects.reputations.items())
            parts.append(f"声望变化({rep_text})")
        if effects.set_world_flags:
            parts.append(f"世界事件触发: {'、'.join(effects.set_world_flags)}")
        return "；".join(parts) if parts else "江湖局势悄然改变。"
