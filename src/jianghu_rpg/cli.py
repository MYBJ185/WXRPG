from __future__ import annotations

import typer
from rich.console import Console

from jianghu_rpg.engine import GameEngine


app = typer.Typer(help="LongCat + ChromaDB wuxia text RPG demo")
console = Console()


@app.command("init-world")
def init_world() -> None:
    engine = GameEngine(console=console)
    count = engine.init_world()
    console.print(f"已初始化 {count} 条武侠世界资料到 ChromaDB。")


@app.command("new")
def new_game(slot: str = typer.Option("autosave", help="存档名")) -> None:
    engine = GameEngine(console=console)
    state = engine.create_character_interactive(slot=slot)
    engine.save_game(state, slot)
    engine.run(state)


@app.command("demo")
def demo_game(slot: str = typer.Option("demo_hero", help="演示存档名")) -> None:
    engine = GameEngine(console=console)
    state = engine.create_demo_state(slot=slot)
    engine.save_game(state, slot)
    engine.run(state)


@app.command("load")
def load_game(slot: str = typer.Option(..., help="要读取的存档名")) -> None:
    engine = GameEngine(console=console)
    state = engine.load_game(slot)
    engine.run(state)


@app.command("saves")
def list_saves() -> None:
    engine = GameEngine(console=console)
    saves = engine.list_saves()
    if not saves:
        console.print("当前没有存档。")
        return
    for save in saves:
        console.print(save)
