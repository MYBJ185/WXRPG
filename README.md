# LongCat Jianghu RPG Demo

一个基于 `LongCat API` + `ChromaDB` 的武侠文字冒险项目，支持：

- 自然语言剧情行动（不只数字选项）
- 自然语言系统指令（背包/状态/存档/切档/退出等）
- 背包、装备、属性、检定、派系与多结局剧情

## 5 分钟部署（Windows / PowerShell）

### 1. 创建并安装环境

```powershell
conda env create -f environment.yml
conda run -n longcat-rpg python -m pip install -e .
```

### 2. 配置环境变量

```powershell
Copy-Item .env.example .env
```

然后编辑 `.env`：

- 配置 `LONGCAT_API_KEY`：启用 LongCat 叙事
- 不配 Key 也可运行：会走本地回退叙事

### 3. 初始化世界知识库（首次或数据更新后执行）

```powershell
conda run -n longcat-rpg python -m jianghu_rpg init-world
```

### 4. 启动游戏

```powershell
conda run -n longcat-rpg python -m jianghu_rpg demo
```

也可以新建角色：

```powershell
conda run -n longcat-rpg python -m jianghu_rpg new
```

## 游戏内常用操作

- 数字选项：`1` `2` `3`
- 自然语言行动：`潜入后院偷听`、`绕到屋后观察脚印`
- 查询命令：`/背包`、`/状态`
- 存档相关：`保存到 test1`、`切换存档 demo_hero`、`存档列表`
- 退出：`退出游戏` 或 `/quit`
- 查看全部命令：`h`

## 读取已有存档

```powershell
conda run -n longcat-rpg python -m jianghu_rpg load --slot demo_hero
```

## 目录结构

- `data/world/`：世界观与物品定义
- `data/story/`：剧情节点与输出规则
- `storage/chroma/`：ChromaDB 持久化目录
- `saves/`：JSON 存档

## 常见问题

- 启动报 `No module named jianghu_rpg`
  先执行：`conda run -n longcat-rpg python -m pip install -e .`
- 想关闭 LongCat，只用本地引擎
  在 `.env` 中设置 `JIANGHU_USE_LONGCAT=false` 或清空 `LONGCAT_API_KEY`
