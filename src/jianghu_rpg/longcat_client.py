from __future__ import annotations

import json
import re

from openai import OpenAI

from jianghu_rpg.config import settings
from jianghu_rpg.models import Choice, FreeActionPlan, GameState, RollOutcome, StoryNode


class LongCatNarrator:
    def __init__(self) -> None:
        self.enabled = bool(settings.jianghu_use_longcat and settings.longcat_api_key)
        self.client = None
        if self.enabled:
            self.client = OpenAI(
                api_key=settings.longcat_api_key,
                base_url=settings.longcat_base_url,
            )

    def describe_scene(
        self,
        state: GameState,
        node: StoryNode,
        lore_context: list[dict[str, str]],
        last_result: RollOutcome | None = None,
        last_choice: Choice | None = None,
    ) -> str | None:
        if not self.enabled or self.client is None:
            return None

        character = state.character
        lore_text = "\n\n".join(
            f"[{entry['title']}] {entry['text']}" for entry in lore_context[:4]
        )
        result_text = "无"
        if last_result and last_choice:
            outcome = "成功" if last_result.success else "失败"
            result_text = (
                f"上一动作：{last_choice.label}；检定：{last_result.roll}+"
                f"{last_result.modifier}+{last_result.bonus}={last_result.total}，"
                f"难度 {last_result.dc}，结果 {outcome}。"
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "你是武侠文字冒险的叙事主持人。"
                    "请只基于给定世界观与状态写 220 到 380 字的中文场景描写。"
                    "风格要求冷峻、克制、具有江湖纵深感。"
                    "请自然分为 2 到 4 段。"
                    "若出现人物对白，请使用中文引号“”或 人名：台词。"
                    "不要替玩家做选择，不要改写数值和规则。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"角色：{character.name}，出身 {character.origin}，取向 {character.tendency}，"
                    f"等级 {character.level}，HP {character.hp}/{character.max_hp}，"
                    f"Qi {character.qi}/{character.max_qi}。\n"
                    f"当前章节：{node.chapter}\n"
                    f"场景标题：{node.title}\n"
                    f"地点：{node.location}\n"
                    f"基础剧情：{node.body}\n"
                    f"{result_text}\n"
                    f"可用世界观：\n{lore_text}"
                ),
            },
        ]
        return self._chat_completion(
            messages=messages,
            temperature=0.72,
            max_tokens=700,
        )

    def describe_resolution(
        self,
        state: GameState,
        current_node: StoryNode,
        next_node: StoryNode,
        choice: Choice,
        lore_context: list[dict[str, str]],
        outcome: RollOutcome | None = None,
    ) -> str | None:
        if not self.enabled or self.client is None:
            return None

        result_text = "本次行动不需要检定。"
        if outcome is not None:
            result_text = (
                f"检定属性：{outcome.stat}；掷骰 {outcome.roll}；"
                f"修正 {outcome.modifier}；额外加值 {outcome.bonus}；"
                f"总计 {outcome.total}；难度 {outcome.dc}；"
                f"结果：{'成功' if outcome.success else '失败'}。"
            )
        lore_text = "\n".join(
            f"- {entry['title']}：{entry['text'][:100]}" for entry in lore_context[:3]
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "你是武侠文字冒险的主持人。"
                    "请用 120 到 220 字中文描写行动结果，强调因果、人物情绪与江湖余波。"
                    "请自然分段，并将人物对白写成“台词”或 人名：台词。"
                    "必须尊重给定检定和场景转换，不要添加新的规则判定。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"玩家角色：{state.character.name}，取向 {state.character.tendency}。\n"
                    f"当前场景：{current_node.title} @ {current_node.location}\n"
                    f"所选行动：{choice.label} - {choice.description}\n"
                    f"{result_text}\n"
                    f"下一个场景：{next_node.title} @ {next_node.location}\n"
                    f"世界背景：\n{lore_text}"
                ),
            },
        ]
        return self._chat_completion(
            messages=messages,
            temperature=0.9,
            max_tokens=420,
        )

    def plan_free_action(
        self,
        state: GameState,
        node: StoryNode,
        action_text: str,
        lore_context: list[dict[str, str]],
        candidate_nodes: list[tuple[str, str, str]],
        known_item_ids: list[str],
        factions: list[str],
    ) -> FreeActionPlan | None:
        if not self.enabled or self.client is None:
            return None

        lore_text = "\n".join(
            f"- {entry['title']}（{entry['category']}）：{entry['text'][:160]}"
            for entry in lore_context[:4]
        )
        node_text = "\n".join(
            f"- {node_id}: {title} @ {location}"
            for node_id, title, location in candidate_nodes
        )
        visible_flags = "、".join(state.world.flags[-8:]) if state.world.flags else "无"
        world_flags = "、".join(state.world.world_flags[-6:]) if state.world.world_flags else "无"
        items_text = "、".join(known_item_ids)
        factions_text = "、".join(factions)

        messages = [
            {
                "role": "system",
                "content": (
                    "你是武侠文字 RPG 的导演裁定器。"
                    "请把玩家自由行动裁定为结构化 JSON。"
                    "必须输出且仅输出一个 JSON 对象，不要 markdown，不要解释。"
                    "JSON schema: "
                    "{"
                    "\"narrative\": \"string(80-260字)\", "
                    "\"next_node\": \"string|null\", "
                    "\"location\": \"string|null\", "
                    "\"effects\": {"
                    "\"xp\": int, \"silver\": int, \"hp\": int, \"qi\": int, "
                    "\"add_items\": {\"item_id\": int}, \"remove_items\": {\"item_id\": int}, "
                    "\"reputations\": {\"faction\": int}, "
                    "\"set_flags\": [string], \"clear_flags\": [string], "
                    "\"set_world_flags\": [string], \"clear_world_flags\": [string], "
                    "\"faction_states\": {\"faction\": \"state\"}, "
                    "\"location_states\": {\"location\": \"state\"}, "
                    "\"rumors\": [string], \"allies\": [string], "
                    "\"chapter_shift\": int, \"time_advance\": int, \"unlock_talents\": [string]"
                    "}"
                    "}"
                    "数值约束：xp -10..40, silver -50..50, hp/qi -8..8, 声望单项 -3..3, time_advance 0..3。"
                    "若行动没有明确时间跨度，请把 time_advance 设为 0。"
                    "可大幅偏离既有剧情，但要保持因果连贯。"
                    "next_node 只能从候选节点中选，若不切换填 null。"
                    "add_items/remove_items 只能使用给定 item_id。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"玩家行动：{action_text}\n"
                    f"角色：{state.character.name}，取向 {state.character.tendency}，"
                    f"等级 {state.character.level}，HP {state.character.hp}/{state.character.max_hp}，"
                    f"Qi {state.character.qi}/{state.character.max_qi}，银钱 {state.character.silver}。\n"
                    f"当前节点：{node.id} - {node.title} @ {node.location}\n"
                    f"当前剧情提示：{node.body}\n"
                    f"可见剧情旗标：{visible_flags}\n"
                    f"可见世界旗标：{world_flags}\n"
                    f"可用阵营键：{factions_text}\n"
                    f"可用物品ID：{items_text}\n"
                    f"可跳转候选节点：\n{node_text}\n"
                    f"补充世界背景：\n{lore_text}"
                ),
            },
        ]
        raw = self._chat_completion(messages=messages, temperature=0.95, max_tokens=1000)
        if raw is None:
            return None
        payload = self._extract_json_object(raw)
        if payload is None:
            return None
        try:
            plan = FreeActionPlan.model_validate(payload)
        except Exception:
            return None
        effects_payload = payload.get("effects", {}) if isinstance(payload, dict) else {}
        if not isinstance(effects_payload, dict) or "time_advance" not in effects_payload:
            plan.effects.time_advance = 0
        return plan

    def _chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str | None:
        if self.client is None:
            return None
        try:
            response = self.client.chat.completions.create(
                model=settings.longcat_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception:
            return None

    @staticmethod
    def _extract_json_object(text: str) -> dict | None:
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
        candidate = fenced.group(1) if fenced else ""
        if not candidate:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                return None
            candidate = text[start : end + 1]
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None
