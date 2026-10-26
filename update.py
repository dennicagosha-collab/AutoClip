"""Автообновление AutoClip через релизы на GitHub.

При запуске программа спрашивает GitHub о последнем релизе. Если он новее — скачивает архив
и заменяет только файлы программы. Прежние файлы откладываются в папку «прежняя версия»,
пользовательские данные в %APPDATA%\\AutoClip не трогаются.

Из консоли:  python update.py           — проверить и обновить
             python update.py --check   — только проверить
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

import autoclip
from autoclip import AutoClipError

VERSION = "2.3.1"
REPO = "dennicagosha-collab/AutoClip"   # пусто — обновления выключены
API = "https://api.github.com/repos/{repo}/releases/latest"

APP_DIR = autoclip.SCRIPT_DIR
BACKUP_NAME = "прежняя версия"
MANIFEST_NAME = "файлы программы.json"
NEEDED = ("app.py", "autoclip.py", "update.py")    # без них архив — не AutoClip
CHANGELOG = os.path.join(APP_DIR, "ЧТО_НОВОГО.md")


def parse_changelog(text):
    """«## 1.1.0 — дата» + пункты «- …» → [{version, date, items}], новые сверху."""
    out = []
    for line in text.splitlines():
        m = re.match(r"##\s+v?(\d+(?:\.\d+){0,2})\s*(?:[—–-]\s*(.+))?$", line.strip())
        if m:
            out.append({"version": m.group(1), "date": (m.group(2) or "").strip(), "items": []})
        elif out and line.strip().startswith(("- ", "* ")):
            out[-1]["items"].append(line.strip()[2:].strip())
        elif out and out[-1]["items"] and line.startswith("  ") and line.strip():
            out[-1]["items"][-1] += " " + line.strip()      # перенос длинного пункта
    out.sort(key=lambda e: parse_version(e["version"]) or (0,), reverse=True)
    return out


def changelog(path=None):
    try:
        with open(path or CHANGELOG, encoding="utf-8") as f:
            return parse_changelog(f.read())
    except OSError:
        return []


def news_since(seen, entries=None):
    """Версии новее seen и не новее текущей — что показать после обновления."""
    entries = changelog() if entries is None else entries
    cur, old = parse_version(VERSION), parse_version(seen or "0")
    return [e for e in entries
            if old < (parse_version(e["version"]) or (0,)) <= (cur or (0,))]


def release_notes(version=None):
    """Текст «Что нового» этой версии — для релиза на GitHub."""
    v = parse_version(version or VERSION)
    for e in changelog():
        if parse_version(e["version"]) == v:
            return "\n".join(f"- {i}" for i in e["items"])
    return ""


def parse_version(text):
    """«v1.2.3» → (1, 2, 3). Непонятное — None."""
    m = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text).strip())
    return tuple(int(x or 0) for x in m.groups()) if m else None


def is_newer(remote, local=None):
    r, l = parse_version(remote), parse_version(local or VERSION)
    return bool(r and l and r > l)


def _get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": f"AutoClip/{VERSION}",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def latest(repo=None, timeout=6):
    """Последний релиз: {version, notes, url, size}. Нет релизов — None."""
    repo = repo if repo is not None else REPO
    if not repo:
        return None
    try:
        with _get(API.format(repo=repo), timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:                       # репозиторий есть, релизов ещё нет
            return None
        raise AutoClipError(f"❌ GitHub ответил ошибкой {e.code}. Попробуй позже.")
    except (urllib.error.URLError, OSError, ValueError):
        raise AutoClipError("❌ Не получилось связаться с GitHub. Проверь интернет.")
    asset = next((a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".zip")),
                 None)
    body = (data.get("body") or "").strip()
    m = re.search(r"SHA-256:\s*([0-9a-fA-F]{64})", body)
    notes = re.sub(r"\n*SHA-256:\s*[0-9a-fA-F]{64}\s*", "", body).strip()
    return {"version": str(data.get("tag_name", "")).lstrip("v"), "notes": notes,
            "url": asset["browser_download_url"] if asset else data.get("zipball_url"),
            "size": asset.get("size") if asset else None,
            "sha256": m.group(1).lower() if m else None}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(repo=None, skip=None, timeout=6):
    """Есть ли версия новее текущей (и не пропущенная пользователем)."""
    rel = latest(repo, timeout)
    if rel and is_newer(rel["version"]) and rel["version"] != skip and rel["url"]:
        return rel
    return None


def download(url, dest, progress=None, cancel=None, timeout=30):
    """Скачать архив релиза. progress(доля 0..1)."""
    try:
        with _get(url, timeout) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if cancel and cancel.is_set():
                    raise autoclip.Cancelled()
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done / total)
    except (urllib.error.URLError, OSError) as e:
        raise AutoClipError(f"❌ Обновление не скачалось: {e}")
    return dest


def _program_files(root):
    """Файлы программы внутри распакованного архива (относительные пути с «/»)."""
    out = []
    for d, _, files in os.walk(root):
        for name in files:
            out.append(os.path.relpath(os.path.join(d, name), root).replace("\\", "/"))
    return sorted(out)


def _unpack(zip_path, into):
    """Распаковать и вернуть папку, где лежит app.py (у архивов GitHub всё внутри одной папки)."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            for n in z.namelist():
                parts = n.replace("\\", "/").split("/")
                if n.startswith(("/", "\\")) or ".." in parts or ":" in parts[0]:
                    raise AutoClipError("❌ В архиве обновления странные пути — не ставлю его.")
            z.extractall(into)
    except zipfile.BadZipFile:
        raise AutoClipError("❌ Архив обновления повреждён. Попробуй ещё раз.")
    root = into
    while True:
        items = os.listdir(root)
        if len(items) == 1 and os.path.isdir(os.path.join(root, items[0])):
            root = os.path.join(root, items[0])
        else:
            break
    if not all(os.path.isfile(os.path.join(root, n)) for n in NEEDED):
        raise AutoClipError("❌ Архив не похож на AutoClip — не ставлю его.")
    return root


def _same(a, b):
    if os.path.getsize(a) != os.path.getsize(b):
        return False
    h = [hashlib.sha256(open(p, "rb").read()).digest() for p in (a, b)]
    return h[0] == h[1]


def is_git_checkout(app_dir=APP_DIR):
    return os.path.isdir(os.path.join(app_dir, ".git"))


import recover as _recover  # noqa: E402  (отдельно: app.py зовёт его раньше всего)

JOURNAL_NAME = _recover.JOURNAL_NAME
recover = _recover.recover


def install(zip_path, app_dir=APP_DIR, expect_sha=None):
    """Поставить скачанный архив. Прежние файлы программы уезжают в «прежняя версия»,
    чужие файлы в папке (записи, клипы, ярлыки) не трогаются.
    Возвращает {"changed": N, "removed": N, "need_install": bool}."""
    backup = os.path.join(app_dir, BACKUP_NAME)
    manifest = os.path.join(app_dir, MANIFEST_NAME)
    journal = os.path.join(app_dir, JOURNAL_NAME)
    if expect_sha is not None and sha256(zip_path) != expect_sha.lower():
        raise AutoClipError("❌ Архив обновления скачался с ошибкой (сумма SHA-256 не совпала). "
                            "Ничего не менял — попробуй позже.")
    with tempfile.TemporaryDirectory(prefix="autoclip_update_") as tmp:
        src = _unpack(zip_path, tmp)
        new = _program_files(src)
        try:
            old = json.load(open(manifest, encoding="utf-8"))
        except (OSError, ValueError):
            old = []
        changed = [f for f in new if not (os.path.isfile(os.path.join(app_dir, f))
                                          and _same(os.path.join(src, f), os.path.join(app_dir, f)))]
        removed = [f for f in old if f not in new and os.path.isfile(os.path.join(app_dir, f))]
        if os.path.exists(backup):
            autoclip.trash(backup)                 # позапрошлая версия — в корзину, не насовсем
        moved = []
        try:
            for f in changed + removed:
                cur = os.path.join(app_dir, f)
                if os.path.isfile(cur):
                    dst = os.path.join(backup, f)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(cur, dst)
                    moved.append(f)
            # сначала новые файлы рядом (.new), потом журнал, потом быстрые замены на месте:
            # выключили свет посередине — при запуске recover() вернёт прежнюю версию
            for f in changed:
                dst = os.path.join(app_dir, f)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(os.path.join(src, f), dst + ".new")
            added = [f for f in changed if f not in moved]
            with open(journal, "w", encoding="utf-8") as fh:
                json.dump({"changed": changed, "removed": removed, "added": added}, fh, ensure_ascii=False)
            for f in changed:
                dst = os.path.join(app_dir, f)
                os.replace(dst + ".new", dst)
            for f in removed:
                os.remove(os.path.join(app_dir, f))   # копия лежит в «прежняя версия»
        except OSError as e:
            for f in moved:                           # что-то пошло не так — возвращаем как было
                try:
                    shutil.copy2(os.path.join(backup, f), os.path.join(app_dir, f))
                except OSError:
                    pass
            for f in changed:
                if f not in moved:
                    try:
                        os.remove(os.path.join(app_dir, f))
                    except OSError:
                        pass
            for f in changed:
                try:
                    os.remove(os.path.join(app_dir, f) + ".new")
                except OSError:
                    pass
            if os.path.exists(journal):
                os.remove(journal)
            raise AutoClipError(f"❌ Обновление не встало, вернул прежнюю версию: {e}")
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump(new, fh, ensure_ascii=False, indent=1)
        os.remove(journal)                             # всё на месте — обновление закончено
    return {"changed": len(changed), "removed": len(removed),
            "need_install": "install.bat" in changed}


def update_git(version, app_dir=APP_DIR):
    """Папка программы — репозиторий git (так её дорабатывают через Claude Code):
    подтягиваем метку релиза, если своих несохранённых изменений нет."""
    def git(*args):
        return subprocess.run(["git", *args], cwd=app_dir, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        if git("status", "--porcelain", "--untracked-files=no").stdout.strip():
            raise AutoClipError("❌ В папке программы есть несохранённые изменения. "
                                "Обнови через Claude Code.")
        tag = f"v{version}"
        r = git("fetch", "--quiet", "origin", "tag", tag)
        if r.returncode:
            raise AutoClipError(f"❌ Не получилось скачать версию {version}: {r.stderr.strip()}")
        before = git("rev-parse", "HEAD").stdout.strip()
        r = git("merge", "--ff-only", "--quiet", tag)
        if r.returncode:
            raise AutoClipError("❌ Версия на GitHub разошлась с этой папкой. "
                                "Обнови через Claude Code.")
        changed = git("diff", "--name-only", before, "HEAD").stdout.split()
    except FileNotFoundError:
        raise AutoClipError("❌ Не найден git — обнови через Claude Code.")
    return {"changed": len(changed), "removed": 0, "need_install": "install.bat" in changed}


def apply(rel, progress=None, cancel=None, app_dir=APP_DIR):
    """Скачать и поставить релиз из check()."""
    if is_git_checkout(app_dir):
        return update_git(rel["version"], app_dir)
    with tempfile.TemporaryDirectory(prefix="autoclip_dl_") as tmp:
        z = download(rel["url"], os.path.join(tmp, "AutoClip.zip"), progress, cancel)
        if not rel.get("sha256"):
            raise AutoClipError("❌ У релиза нет контрольной суммы SHA-256 — ставить не буду.")
        return install(z, app_dir, expect_sha=rel["sha256"])


def restart(need_install=False, app_dir=APP_DIR):
    """Запустить программу заново (или сначала install.bat, если поменялись библиотеки)."""
    if need_install:
        os.startfile(os.path.join(app_dir, "install.bat"))
        return
    exe = sys.executable
    if exe.lower().endswith("python.exe") and os.path.isfile(exe[:-10] + "pythonw.exe"):
        exe = exe[:-10] + "pythonw.exe"
    subprocess.Popen([exe, os.path.join(app_dir, "app.py"), "--after-update"], cwd=app_dir,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Обновление AutoClip")
    ap.add_argument("--check", action="store_true", help="только проверить")
    ap.add_argument("--repo", default=None, help="репозиторий GitHub «ник/имя»")
    a = ap.parse_args()
    print(f"AutoClip {VERSION}")
    if not (a.repo or REPO):
        print("Репозиторий для обновлений не задан.")
        return
    try:
        rel = check(a.repo)
        if not rel:
            print("Это последняя версия.")
            return
        print(f"Есть версия {rel['version']}.")
        if rel["notes"]:
            print(rel["notes"])
        if a.check:
            return
        res = apply(rel, progress=lambda p: print(f"\r  скачано {p:.0%}", end=""))
        print(f"\nГотово: обновлено файлов {res['changed']}.")
        if res["need_install"]:
            print("В новой версии новые библиотеки — запусти install.bat.")
    except AutoClipError as e:
        print(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
