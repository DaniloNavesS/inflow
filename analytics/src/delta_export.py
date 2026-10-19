"""Snapshot completo do OLTP sincronizado por id, preservando versões Delta."""
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
from deltalake import DeltaTable, WriterProperties, write_deltalake

from duck import PG


def merge_snapshot(data: pa.Table, target: Path) -> dict:
    """Recebe a origem COMPLETA; ausências representam exclusões, não um lote CDC."""
    ids = data["id"]
    if ids.null_count or len(pc.unique(ids)) != data.num_rows:
        raise ValueError("O snapshot deve ter id não nulo e único por despesa.")
    target.parent.mkdir(parents=True, exist_ok=True)
    props = WriterProperties(compression="ZSTD")
    if not DeltaTable.is_deltatable(target):
        write_deltalake(target, data, writer_properties=props)
        metrics = {"num_target_rows_inserted": data.num_rows}
    else:
        changed = " OR ".join(
            f'(t."{name}" IS DISTINCT FROM s."{name}")'
            for name in data.column_names if name != "id"
        )
        metrics = (
            DeltaTable(target).merge(
                data, predicate="t.id = s.id", source_alias="s", target_alias="t",
                writer_properties=props,
            )
            .when_matched_update_all(predicate=changed)
            .when_not_matched_insert_all()
            .when_not_matched_by_source_delete()
            .execute()
        )
    return {"linhas": data.num_rows, "versao": DeltaTable(target).version(), **metrics}


def export_despesas(con, lake_dir: Path) -> dict:
    data = con.execute(f"SELECT * FROM {PG}.oltp.despesas ORDER BY id").to_arrow_table()
    return merge_snapshot(data, lake_dir / "delta" / "despesas")
