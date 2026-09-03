"""Dataset endpoints: generate ground-truth data, or upload your own files."""

from __future__ import annotations

import uuid

import polars as pl
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy import select

from app.api.schemas import DatasetInfo, GenerateDatasetRequest
from app.config import settings
from app.data import generator
from app.data.normalizer import load_any
from app.services import run_manager
from app.store.db import session_scope
from app.store.models import Dataset

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("", response_model=DatasetInfo, status_code=201)
def generate_dataset(req: GenerateDatasetRequest) -> DatasetInfo:
    """Generate a synthetic dataset whose anomalies are known in advance.

    This is what makes the accuracy numbers on the benchmark screen defensible:
    the injected truth is retained alongside the corrupted data.
    """
    dataset_id = f"ds-{req.size}-{req.seed}-{uuid.uuid4().hex[:6]}"
    ds = generator.generate(req.size, dataset_id, seed=req.seed)
    generator.persist(ds)
    label = req.label or f"Synthetic {req.size:,} orders (seed {req.seed})"
    run_manager.register_dataset(dataset_id, label, ds)
    return DatasetInfo(
        id=dataset_id, label=label, orders=ds.orders.height,
        payments=ds.payments.height, settlements=ds.settlements.height,
        has_ground_truth=True, meta=ds.stats,
    )


@router.post("/upload", response_model=DatasetInfo, status_code=201)
async def upload_dataset(
    orders: UploadFile = File(...),
    payments: UploadFile = File(...),
    settlements: UploadFile = File(...),
    label: str = Form("Uploaded dataset"),
) -> DatasetInfo:
    """Accept three CSV/Parquet/JSON files. Columns are auto-detected."""
    dataset_id = f"up-{uuid.uuid4().hex[:10]}"
    root = settings.dataset_dir(dataset_id)
    root.mkdir(parents=True, exist_ok=True)

    frames: dict[str, pl.DataFrame] = {}
    for name, upload in (("orders", orders), ("payments", payments), ("settlements", settlements)):
        raw = root / f"raw_{name}{_suffix(upload.filename)}"
        raw.write_bytes(await upload.read())
        try:
            df = load_any(raw)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"could not parse {name}: {exc}") from exc
        df.write_parquet(root / f"{name}.parquet")
        frames[name] = df

    with session_scope() as s:
        s.merge(Dataset(
            id=dataset_id, label=label, kind="uploaded",
            orders=frames["orders"].height, payments=frames["payments"].height,
            settlements=frames["settlements"].height, has_ground_truth=False,
            meta={"columns": {k: v.columns for k, v in frames.items()}},
        ))

    return DatasetInfo(
        id=dataset_id, label=label, orders=frames["orders"].height,
        payments=frames["payments"].height, settlements=frames["settlements"].height,
        has_ground_truth=False,
    )


@router.get("", response_model=list[DatasetInfo])
def list_datasets() -> list[DatasetInfo]:
    with session_scope() as s:
        rows = s.execute(select(Dataset).order_by(Dataset.created_at.desc()).limit(100)).scalars().all()
        return [
            DatasetInfo(
                id=d.id, label=d.label, orders=d.orders, payments=d.payments,
                settlements=d.settlements, has_ground_truth=d.has_ground_truth,
                created_at=d.created_at, meta=d.meta or {},
            )
            for d in rows
        ]


def _suffix(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ".csv"
    return "." + filename.rsplit(".", 1)[-1].lower()
