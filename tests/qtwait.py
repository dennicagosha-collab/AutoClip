"""Ожидание в тестах окна. QTest.qWait в PySide почти не даёт работать потокам Python
(фоновая пересборка, предпросмотр) — ждём настоящим циклом событий, как в программе."""


def pump(ms):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(int(ms), loop.quit)
    loop.exec()
