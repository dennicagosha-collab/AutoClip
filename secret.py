# -*- coding: utf-8 -*-
"""Шифрование секретов средствами Windows (DPAPI, P3): токен Telegram-бота лежит в telegram.json
зашифрованным под этого пользователя Windows — скопированный на другой компьютер файл бесполезен.
В резервной копии (3Б.9) токен хранится открыто (manifest "secrets": "plain"), чтобы копия
восстанавливалась и на новой Windows; после восстановления программа снова его шифрует."""

import base64
import ctypes
import os
from ctypes import wintypes

PREFIX = "dpapi:"


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def available():
    return os.name == "nt"


def protect(text):
    """Строка → «dpapi:…» (base64 зашифрованного). Не Windows — как есть."""
    if not text or not available() or str(text).startswith(PREFIX):
        return text
    src, _keep = _blob(str(text).encode("utf-8"))
    out = _BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(src), "AutoClip", None, None, None,
                                                   0x01, ctypes.byref(out)):    # без окон
        return text
    try:
        data = ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)
    return PREFIX + base64.b64encode(data).decode("ascii")


def unprotect(text):
    """«dpapi:…» → исходная строка; не зашифровано — как есть; не расшифровалось (другой
    пользователь/компьютер) — None."""
    if not text or not str(text).startswith(PREFIX):
        return text
    if not available():
        return None
    raw = base64.b64decode(str(text)[len(PREFIX):])
    src, _keep = _blob(raw)
    out = _BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None,
                                                     0x01, ctypes.byref(out)):
        return None
    try:
        return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)
