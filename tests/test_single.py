"""Одна копия программы: второй запуск показывает окно первой и выходит."""
import os
import subprocess
import sys
import uuid

import pytest

pytest.importorskip("PySide6")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_second_copy_hands_over_and_exits():
    from PySide6.QtWidgets import QApplication
    from qtwait import pump
    import app as A
    qapp = QApplication.instance() or QApplication([])  # noqa: F841
    name = "AutoClipTest-" + uuid.uuid4().hex[:8]
    got = []
    server = A.InstanceServer(got.append, name)
    try:
        assert not A.ping_running("AutoClipTest-нет-такой")      # первой копии нет — запускаемся
        # «вторая копия» — отдельный процесс: находит первую, передаёт «показать» и выходит
        code = ("import sys; sys.path.insert(0, r'%s'); import os; os.environ['QT_QPA_PLATFORM']='offscreen';"
                "from PySide6.QtWidgets import QApplication; q=QApplication([]); import app;"
                "sys.exit(0 if app.ping_running(%r) else 3)") % (HERE, name)
        p = subprocess.Popen([sys.executable, "-c", code])
        for _ in range(200):
            pump(50)
            if p.poll() is not None and got:
                break
        assert p.wait(10) == 0 and got == ["show"]
    finally:
        server.close()
    assert not A.ping_running(name)                               # закрылась — места свободно
