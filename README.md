# LongCat Jianghu RPG Demo

一个基于 `LongCat API` 和 `ChromaDB` 本地向量库的武侠文字冒险 demo。

## 功能

- LongCat(OpenAI 兼容) 叙事层，可选开启
- ChromaDB 本地向量库存储武侠世界设定与剧情知识
- DND 风格属性检定：`d20 + 属性修正 + 装备加成`
- 完整背包系统：堆叠、装备、使用、容量、金钱
- 多存档系统：可自定义角色并保留成长状态
- 世界状态演化：派系、地点、谣言、事件会持续变化
- 完整多幕剧情，支持多结局

## LongCat 调研结论

- LongCat 提供 OpenAI 兼容接口，官方文档与官网示例均展示了通过 OpenAI SDK 接入的方式，默认模型示例为 `longcat-flash-chat`。在本项目中可直接通过 `base_url` 切到 LongCat 网关，无需重写调用框架。
- 建议通过环境变量提供 `LONGCAT_API_KEY`，并将 `LONGCAT_BASE_URL` 设为 `https://api.longcat.chat/openai/v1`。
- 如果未配置 Key，本 demo 会自动退回到本地剧情引擎，保证仍可完整游玩。

## 创建环境

```powershell
conda env create -f environment.yml
conda run -n longcat-rpg python -m pip install -e .
```

## 初始化世界库

```powershell
conda run -n longcat-rpg python -m jianghu_rpg init-world
```

## 开始新游戏

```powershell
conda run -n longcat-rpg python -m jianghu_rpg new
```

## 读取存档

```powershell
conda run -n longcat-rpg python -m jianghu_rpg load --slot demo_hero
```

## 目录结构

- `data/world/`: 武侠世界观、物品定义
- `data/story/`: 剧情节点
- `storage/chroma/`: ChromaDB 持久化目录
- `saves/`: JSON 存档

## 说明

- 世界观采用结构化文档写入 ChromaDB，本地检索结果会参与场景叙事。
- LongCat 开启后，场景描写会更灵活，但核心逻辑、数值与分支仍由本地引擎控制。
