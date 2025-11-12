from dataclasses import dataclass
from typing import List

@dataclass
class Shot:
    duration: float
    camera: str
    composition: str
    action: str

def build_shots(prompt: str) -> List[Shot]:
    p = (prompt or "").lower()
    base = [
        Shot(1.5, "медленный съезд", "средний план", "установочный ритм"),
        Shot(2.0, "наезд", "крупный план", "выделяем главный объект"),
        Shot(1.5, "панорама", "общий план", "контекст сцены"),
    ]
    if any(w in p for w in ["море","пляж","ocean","sea"]):
        base[0].action = "волны, ветер; установочный шот"
        base[1].action = "наезд на персонажа у кромки воды"
    if any(w in p for w in ["камин","огонь","fire"]):
        base[0].action = "тёплый свет, камин; уютный сеттинг"
        base[1].action = "крупно: лицо/руки в свете огня"
    if any(w in p for w in ["ветер","буря","wind"]):
        base[2].action = "панорама: качание волос/тканей"
    return base

def summarize_plan(shots: List[Shot]) -> str:
    lines = []
    for i, s in enumerate(shots, 1):
        lines.append(f"{i}) {s.duration:.1f}с — {s.camera}, {s.composition}, {s.action}")
    return "\n".join(lines)
