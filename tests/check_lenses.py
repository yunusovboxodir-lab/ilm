"""Check every lens in lenses/: structure, size, vocabulary. Run:  python tests/check_lenses.py"""
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "lenses"
MAX_CHARS = 7000          # must fit the standing-instructions field of chat apps
TERMS = (18, 22)
SECTIONS = ["## Как говорить", "## Словарь", "## Карта проекта", "## Вопросы для проверки"]
HEADER = ["Основа:", "Когда помогает:", "Как подключить:"]


def check(path):
    text = io.open(path, encoding="utf-8").read()
    errors = []
    if not text.startswith("# Линза: "):
        errors.append("first line must be '# Линза: ...'")
    for h in HEADER:
        if h not in text.split("---", 1)[0]:
            errors.append(f"header line '{h}' is missing above the divider")
    if text.count("\n---\n") != 1:
        errors.append("exactly one '---' divider is expected")
    body = text.split("\n---\n", 1)[-1]
    pos = [body.find(s) for s in SECTIONS]
    if -1 in pos or pos != sorted(pos):
        errors.append("sections missing or out of order: " + ", ".join(SECTIONS))
    if len(body) > MAX_CHARS:
        errors.append(f"text below the divider is {len(body)} chars, limit {MAX_CHARS}")
    rules = re.findall(r"(?m)^\d+\. ", body.split("## Словарь")[0])
    if len(rules) != 8:
        errors.append(f"'Как говорить' must have 8 numbered rules, found {len(rules)}")
    table = body.split("## Словарь", 1)[-1].split("## Карта проекта")[0]
    rows = [r for r in table.splitlines() if r.startswith("|")][2:]
    if not TERMS[0] <= len(rows) <= TERMS[1]:
        errors.append(f"vocabulary has {len(rows)} terms, expected {TERMS[0]}-{TERMS[1]}")
    names = []
    for r in rows:
        cells = [c.strip() for c in r.strip("|").split("|")]
        if len(cells) != 3 or not all(cells):
            errors.append("row must have three filled cells: " + r[:50])
            continue
        names.append(cells[0].lower())
        if len(cells[1]) > 70:
            errors.append(f"meaning longer than 70 chars: {cells[0]}")
        if len(cells[2]) > 110:
            errors.append(f"project example longer than 110 chars: {cells[0]}")
    if len(set(names)) != len(names):
        errors.append("a term is listed twice")
    project_map = body.split("## Карта проекта")[-1].split("## Вопросы для проверки")[0].strip()
    if not project_map.startswith("Когда я прошу «составь карту проекта»"):
        errors.append("the project map must start with: Когда я прошу «составь карту проекта», ...")
    if not project_map.endswith("Чего не знаешь, спроси, а не выдумывай."):
        errors.append("the project map must end with: Чего не знаешь, спроси, а не выдумывай.")
    questions = [q for q in body.split("## Вопросы для проверки")[-1].splitlines() if q.startswith("- ")]
    if not 4 <= len(questions) <= 6:
        errors.append(f"expected 4-6 check questions, found {len(questions)}")
    if re.search(r"[«\"][^»\"]{120,}[»\"]", body):
        errors.append("long quotation found: lenses are written in our own words")
    if re.search(r"\b(стр\.|с\.|p\.)\s*\d", body):
        errors.append("page reference found: lenses carry no page numbers")
    return len(body), len(rows), errors


def main():
    files = sorted(p for p in ROOT.glob("*.md") if p.name[:2].isdigit())
    failed = 0
    for p in files:
        size, terms, errors = check(p)
        print(f"{'FAIL' if errors else 'ok  '} {p.name:40} {size:5} chars {terms:3} terms")
        for e in errors:
            print("       -", e)
        failed += bool(errors)
    print(f"{len(files)} lenses, {failed} failed")
    return 1 if failed or not files else 0


if __name__ == "__main__":
    sys.exit(main())
