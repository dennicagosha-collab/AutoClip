"""Выпуск новой версии AutoClip на GitHub (для разработки, не для пользователя).

1. Поднять VERSION в update.py и закоммитить.
2. python make_release.py "Что нового: ..."

Скрипт собирает архив из закоммиченных файлов (git archive), ставит метку vX.Y.Z,
отправляет код на GitHub и создаёт релиз с архивом (нужен GitHub CLI — gh).
"""
import os
import shutil
import subprocess
import sys

import update

HERE = os.path.dirname(os.path.abspath(__file__))
GH = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"


def run(*args, capture=False):
    r = subprocess.run(args, cwd=HERE, text=True, encoding="utf-8",
                       capture_output=capture)
    if r.returncode:
        sys.exit(f"Ошибка: {' '.join(args)}\n{(r.stderr or '').strip()}")
    return (r.stdout or "").strip()


def main():
    notes = " ".join(sys.argv[1:]).strip()
    if not notes:
        sys.exit('Напиши, что нового:  python make_release.py "Что нового: ..."')
    if not update.REPO:
        sys.exit("В update.py не задан REPO.")
    if run("git", "status", "--porcelain", "--untracked-files=no", capture=True):
        sys.exit("Есть незакоммиченные изменения — сначала коммит.")
    tag = f"v{update.VERSION}"
    if run("git", "tag", "--list", tag, capture=True):
        sys.exit(f"Метка {tag} уже есть — подними VERSION в update.py.")
    os.makedirs(os.path.join(HERE, "dist"), exist_ok=True)
    zip_path = os.path.join("dist", f"AutoClip-{tag}.zip")
    run("git", "archive", "--format=zip", "--prefix=AutoClip/", "-o", zip_path, "HEAD")
    run("git", "tag", "-a", tag, "-m", f"AutoClip {update.VERSION}")
    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD", capture=True)
    run("git", "push", "origin", branch, tag)
    run(GH, "release", "create", tag, zip_path, "--repo", update.REPO,
        "--title", f"AutoClip {update.VERSION}", "--notes", notes)
    print(f"Готово: {tag} выложен, у пользователей программа предложит обновиться.")


if __name__ == "__main__":
    main()
