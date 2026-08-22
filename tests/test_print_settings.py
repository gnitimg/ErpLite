from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.main import print_settings, update_print_settings
from app.schemas import PrintSettingsPayload


def test_print_settings_have_a4_default_and_persist_custom_size():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        initial = print_settings(db)
        assert initial["paper_preset"] == "A4_LANDSCAPE"
        assert initial["width_mm"] == 297
        assert initial["height_mm"] == 210

        saved = update_print_settings(
            PrintSettingsPayload(
                paper_preset="CUSTOM",
                width_mm=241,
                height_mm=93,
            ),
            db,
        )
        assert saved["paper_preset"] == "CUSTOM"
        assert saved["width_mm"] == 241
        assert saved["height_mm"] == 93
