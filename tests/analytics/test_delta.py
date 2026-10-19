"""Aceite Delta: reexecução, correção com histórico e remoção no snapshot completo."""
from decimal import Decimal

import pytest

pa = pytest.importorskip("pyarrow")
pytest.importorskip("deltalake")
from deltalake import DeltaTable
from delta_export import merge_snapshot


def snapshot(values):
    return pa.table({
        "id": pa.array([key for key, _ in values], type=pa.int64()),
        "valor": pa.array([Decimal(value) for _, value in values], type=pa.decimal128(14, 2)),
    })


def test_rerun_then_correction_keeps_old_version(tmp_path):
    target = tmp_path / "delta" / "despesas"
    data = snapshot([(1, "100.00"), (2, "50.00")])
    first = merge_snapshot(data, target)
    repeat = merge_snapshot(data, target)
    assert repeat["num_target_rows_updated"] == 0
    assert repeat["num_target_rows_inserted"] == 0
    assert DeltaTable(target).to_pyarrow_table().num_rows == 2
    updated = merge_snapshot(snapshot([(1, "101.23"), (2, "50.00"), (3, "20.00")]), target)
    assert updated["versao"] > first["versao"]
    assert updated["num_target_rows_updated"] == 1
    assert updated["num_target_rows_inserted"] == 1
    old = DeltaTable(target, version=first["versao"]).to_pyarrow_table()
    assert sorted(old.to_pylist(), key=lambda row: row["id"]) == data.to_pylist()
    assert DeltaTable(target).to_pyarrow_table().num_rows == 3


def test_full_snapshot_removes_absent_rows_and_handles_empty(tmp_path):
    target = tmp_path / "despesas"
    merge_snapshot(snapshot([(1, "100.00"), (2, "50.00")]), target)
    merge_snapshot(snapshot([(2, "50.00")]), target)
    assert DeltaTable(target).to_pyarrow_table()["id"].to_pylist() == [2]
    merge_snapshot(snapshot([]), target)
    assert DeltaTable(target).to_pyarrow_table().num_rows == 0


def test_duplicate_keys_are_rejected_before_writing(tmp_path):
    with pytest.raises(ValueError, match="único"):
        merge_snapshot(snapshot([(1, "10.00"), (1, "20.00")]), tmp_path / "despesas")


def test_initial_empty_snapshot_has_readable_schema(tmp_path):
    target = tmp_path / "despesas"
    merge_snapshot(snapshot([]), target)
    table = DeltaTable(target).to_pyarrow_table()
    assert table.num_rows == 0 and table.column_names == ["id", "valor"]
