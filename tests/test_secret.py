"""P3: токен Telegram на диске — зашифрован DPAPI; в резервной копии — открыт, восстанавливается."""
import json
import os
import zipfile

import pytest

import backup
import secret
import telegram_bot as tg


@pytest.mark.skipif(os.name != "nt", reason="DPAPI — только Windows")
def test_dpapi_roundtrip():
    enc = secret.protect("123:abc")
    assert enc.startswith(secret.PREFIX) and "123:abc" not in enc
    assert secret.unprotect(enc) == "123:abc"
    assert secret.unprotect("plain") == "plain"                       # старый открытый — как есть
    assert secret.unprotect(secret.PREFIX + "AAAA") is None            # чужой/битый — None, не падаем


@pytest.mark.skipif(os.name != "nt", reason="DPAPI — только Windows")
def test_token_encrypted_on_disk_and_backup_plain(tmp_path, fake_trash):
    tg.save_state({"token": "123:abc", "chat_id": 42})
    disk = json.load(open(tg.STATE_PATH, encoding="utf-8"))
    assert disk["token"].startswith(secret.PREFIX)
    assert tg.load_state()["token"] == "123:abc" and tg.is_connected()
    # старый файл с открытым токеном читается
    json.dump({"token": "9:z", "chat_id": 1}, open(tg.STATE_PATH, "w", encoding="utf-8"))
    assert tg.load_state()["token"] == "9:z"
    # копия: telegram.json кладётся туда как часть данных — с открытым токеном
    import shutil
    root = backup.data_dir()
    shutil.copy(tg.STATE_PATH, os.path.join(root, "telegram.json"))
    monkey_state = tg.STATE_PATH
    tg.save_state({"token": "123:abc", "chat_id": 42})
    shutil.copy(tg.STATE_PATH, os.path.join(root, "telegram.json"))
    z = str(tmp_path / "к.zip")
    backup.save_backup(z)
    inside = json.loads(zipfile.ZipFile(z).read("data/telegram.json").decode("utf-8"))
    assert inside["token"] == "123:abc" and backup.read_manifest(z)["secrets"] == "plain"
