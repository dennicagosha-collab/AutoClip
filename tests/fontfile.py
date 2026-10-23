"""Для тестов: копия шрифта с другим названием семейства — такого шрифта в системе точно нет."""
import struct


def renamed_font(src, dst, family):
    data = bytearray(open(src, "rb").read())
    num = struct.unpack(">H", data[4:6])[0]
    entry = None
    for i in range(num):
        pos = 12 + 16 * i
        if bytes(data[pos:pos + 4]) == b"name":
            entry = pos
    assert entry is not None, "в шрифте нет таблицы name"
    names = {1: family, 2: "Regular", 4: family, 6: family.replace(" ", "")}
    strings, records = b"", []
    for nid, text in names.items():
        raw = text.encode("utf-16-be")
        records.append(struct.pack(">HHHHHH", 3, 1, 0x409, nid, len(raw), len(strings)))
        strings += raw
    table = struct.pack(">HHH", 0, len(records), 6 + 12 * len(records)) + b"".join(records) + strings
    while len(data) % 4:
        data += b"\0"
    off = len(data)
    data += table
    struct.pack_into(">4sIII", data, entry, b"name", 0, off, len(table))
    open(dst, "wb").write(bytes(data))
    return dst
