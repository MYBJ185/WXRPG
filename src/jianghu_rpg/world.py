from __future__ import annotations

import json
from collections import deque
from pathlib import Path

from jianghu_rpg.models import ItemDefinition, StoryNode, WorldDocument


def _load_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


class WorldRepository:
    def __init__(self, world_dir: Path, story_dir: Path):
        self.world_dir = world_dir
        self.story_dir = story_dir
        self._world_docs: list[WorldDocument] | None = None
        self._items: dict[str, ItemDefinition] | None = None
        self._story_nodes: dict[str, StoryNode] | None = None
        self._story_payload_by_id: dict[str, dict] | None = None
        self._story_links_by_id: dict[str, list[str]] | None = None
        self._story_node_cache: dict[str, StoryNode] = {}

    @property
    def world_docs(self) -> list[WorldDocument]:
        if self._world_docs is None:
            payload = _load_json(self.world_dir / "world_docs.json")
            self._world_docs = [WorldDocument.model_validate(item) for item in payload]
        return self._world_docs

    @property
    def items(self) -> dict[str, ItemDefinition]:
        if self._items is None:
            payload = _load_json(self.world_dir / "items.json")
            self._items = {
                item["id"]: ItemDefinition.model_validate(item)
                for item in payload
            }
        return self._items

    @property
    def story_nodes(self) -> dict[str, StoryNode]:
        if self._story_nodes is None:
            self._ensure_story_index()
            assert self._story_payload_by_id is not None
            self._story_nodes = {
                node_id: self.get_story_node(node_id)
                for node_id in self._story_payload_by_id
            }
        return self._story_nodes

    def get_story_node(self, node_id: str) -> StoryNode:
        if node_id in self._story_node_cache:
            return self._story_node_cache[node_id]
        self._ensure_story_index()
        assert self._story_payload_by_id is not None
        payload = self._story_payload_by_id.get(node_id)
        if payload is None:
            raise KeyError(node_id)
        node = StoryNode.model_validate(payload)
        self._story_node_cache[node_id] = node
        return node

    def has_story_node(self, node_id: str) -> bool:
        self._ensure_story_index()
        assert self._story_payload_by_id is not None
        return node_id in self._story_payload_by_id

    def candidate_nodes_near(
        self,
        start_node_id: str,
        depth: int = 1,
        limit: int = 12,
    ) -> list[tuple[str, str, str]]:
        self._ensure_story_index()
        assert self._story_payload_by_id is not None
        assert self._story_links_by_id is not None
        if limit <= 0:
            return []
        depth = max(0, depth)

        results: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        queue: deque[tuple[str, int]] = deque()
        if start_node_id in self._story_payload_by_id:
            queue.append((start_node_id, 0))
            seen.add(start_node_id)

        while queue and len(results) < limit:
            node_id, current_depth = queue.popleft()
            payload = self._story_payload_by_id.get(node_id)
            if payload is None:
                continue
            results.append(
                (
                    node_id,
                    str(payload.get("title", node_id)),
                    str(payload.get("location", "")),
                )
            )
            if current_depth >= depth:
                continue
            for linked in self._story_links_by_id.get(node_id, []):
                if linked in seen or linked not in self._story_payload_by_id:
                    continue
                seen.add(linked)
                queue.append((linked, current_depth + 1))

        if len(results) >= limit:
            return results

        # Keep neighborhood-focused candidates; only fall back when near graph is too sparse.
        fallback_target = min(6, limit)
        if len(results) >= fallback_target:
            return results

        for node_id, payload in self._story_payload_by_id.items():
            if node_id in seen:
                continue
            results.append(
                (
                    node_id,
                    str(payload.get("title", node_id)),
                    str(payload.get("location", "")),
                )
            )
            if len(results) >= fallback_target:
                break
        return results

    def _ensure_story_index(self) -> None:
        if self._story_payload_by_id is not None and self._story_links_by_id is not None:
            return
        payload = _load_json(self.story_dir / "story_nodes.json")
        payload_by_id: dict[str, dict] = {}
        links_by_id: dict[str, list[str]] = {}
        for item in payload:
            node_id = str(item["id"])
            payload_by_id[node_id] = item
            links: list[str] = []
            for choice in item.get("choices", []):
                next_node = choice.get("next_node")
                if isinstance(next_node, str) and next_node:
                    links.append(next_node)
                challenge = choice.get("challenge") or {}
                success_node = challenge.get("success_node")
                failure_node = challenge.get("failure_node")
                if isinstance(success_node, str) and success_node:
                    links.append(success_node)
                if isinstance(failure_node, str) and failure_node:
                    links.append(failure_node)
            links_by_id[node_id] = list(dict.fromkeys(links))
        self._story_payload_by_id = payload_by_id
        self._story_links_by_id = links_by_id
