from threading import RLock

from terp.core import enqueue

_lock = RLock()


def export_notes():
    enqueue('notes.export', {})
