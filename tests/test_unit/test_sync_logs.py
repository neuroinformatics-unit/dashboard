import importlib.util
import io
from pathlib import Path

import pyarrow.parquet as pq

_path = Path(__file__).parents[2] / "scripts" / "sync_logs.py"
_spec = importlib.util.spec_from_file_location("sync_logs", _path)
sync_logs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_logs)


class FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def get_paginator(self, _):
        return self

    def paginate(self, Bucket, StartAfter):
        keys = sorted(k for k in self.objects if k > StartAfter)
        return [{"Contents": [{"Key": k} for k in keys]}]

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}


def _mirrored(out):
    return {
        key: body
        for path in sorted(out.glob("*.parquet"))
        for key, body in zip(*pq.read_table(path).to_pydict().values())
    }


def _sync(s3, out, batch=50_000):
    rows = sync_logs.s3_rows(s3, "b", sync_logs.last_key(out), workers=2)
    return sync_logs.write(out, rows, batch=batch)


def test_sync_appends_only_new_keys(tmp_path):
    out = tmp_path / "mirror"
    s3 = FakeS3(
        {
            "2026-08-12-a": b"\x1f\x8b gz",
            "2026-08-12-b": b"x\r\n",
            "2026-08-12-c": b"",
        }
    )
    assert _sync(s3, out, batch=2) == 3  # 2 appends to one day file
    assert [p.name for p in out.glob("*.parquet")] == ["2026-08-12.parquet"]
    assert sync_logs.last_key(out) == "2026-08-12-c"

    s3.objects["2026-08-12-d"] = b"same day"
    s3.objects["2026-08-13-e"] = b"new day"
    # Changing an already-synced object must not refetch it.
    s3.objects["2026-08-12-a"] = b"changed"
    assert _sync(s3, out) == 2
    assert _sync(s3, out) == 0
    assert sorted(p.name for p in out.glob("*.parquet")) == [
        "2026-08-12.parquet",
        "2026-08-13.parquet",
    ]

    assert _mirrored(out) == {
        "2026-08-12-a": b"\x1f\x8b gz",
        "2026-08-12-b": b"x\r\n",
        "2026-08-12-c": b"",
        "2026-08-12-d": b"same day",
        "2026-08-13-e": b"new day",
    }
    assert not list(out.glob("*.partial"))
