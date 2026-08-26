from pathlib import Path
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models import DocumentNumberRule
from app.schemas import NavigationSettingsPayload
from app.services import serial


def test_document_numbers_use_persistent_configurable_sequence():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        assert serial("SO", db) == "SO000001"
        assert serial("SO", db) == "SO000002"
        db.commit()

    with Session(engine) as db:
        rule = db.scalar(select(DocumentNumberRule).where(
            DocumentNumberRule.document_type == "SO"
        ))
        assert rule is not None
        assert rule.next_number == 3
        rule.prefix = "AA-"
        rule.next_number = 120
        rule.digits = 5
        db.commit()
        assert serial("SO", db) == "AA-00120"


def test_navigation_settings_remove_invalid_and_duplicate_paths():
    payload = NavigationSettingsPayload(
        root_order=["/lite-orders", "bad", "/lite-orders", "/lite-production"],
        hidden_roots=["/lite-finance", "invalid"],
        child_order={
            "/lite-orders": ["list", "list", "documents"],
            "invalid": ["ignored"],
        },
    )
    assert payload.root_order == ["/lite-orders", "/lite-production"]
    assert payload.hidden_roots == ["/lite-finance"]
    assert payload.child_order == {
        "/lite-orders": ["list", "documents"]
    }
