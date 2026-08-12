"""
Single source of truth for config. Every module that needs
poll_interval_minutes / low_stock_threshold / alerts.enabled / etc.
imports `settings` from here - nothing else reads config.yaml directly.
"""
from __future__ import annotations

import os

import yaml
from pydantic import BaseModel

CONFIG_PATH = os.environ.get("TALLY_TRACKER_CONFIG", os.path.join(os.path.dirname(__file__), "config.yaml"))


class TallySettings(BaseModel):
    host: str = "localhost"
    port: int = 9000
    company_name: str = "Your Company Name"


class PollingSettings(BaseModel):
    interval_minutes: int = 5


class AlertsSettings(BaseModel):
    enabled: bool = False


class StockSettings(BaseModel):
    low_stock_threshold: float = 10


class BillingSettings(BaseModel):
    # Used only when Tally gives no due-date signal at all for a bill (no
    # BILLCREDITPERIOD/JD, no explicit credit-period text) - your standard
    # credit terms, applied as bill_date + this many days, so such bills
    # still get a real due date instead of silently sorting to the bottom
    # of Payable/Receivable with no due date shown.
    default_credit_days: int = 30


class DatabaseSettings(BaseModel):
    path: str = "./tally.db"


class Settings(BaseModel):
    tally: TallySettings = TallySettings()
    polling: PollingSettings = PollingSettings()
    alerts: AlertsSettings = AlertsSettings()
    stock: StockSettings = StockSettings()
    billing: BillingSettings = BillingSettings()
    database: DatabaseSettings = DatabaseSettings()


def load_settings(path: str = CONFIG_PATH) -> Settings:
    if not os.path.exists(path):
        return Settings()
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Settings(**raw)


settings = load_settings()
