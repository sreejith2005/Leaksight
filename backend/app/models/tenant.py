"""
LeakSight V1 — Tenant & User Models

Source: docs/DATABASE_SCHEMA.md (Sections 3.1, 3.2, 3.17)

tenants: Top-level tenant table. Not scoped by RLS.
users: Users within a tenant. RLS-scoped.
tenant_settings: Per-tenant configuration. RLS-scoped.
"""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

from backend.app.core.database import Base

# --- Enums ---
user_role_enum = Enum("ADMIN", "REVIEWER", name="user_role_enum", create_type=True)


class Tenant(Base):
    """Top-level tenant table. Not scoped by RLS — used for admin ops."""

    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    name = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class User(Base):
    """Users within a tenant. RLS-scoped by tenant_id."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    email = Column(Text, nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(user_role_enum, nullable=False, server_default="REVIEWER")
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )


# Default abbreviation dictionary per DATABASE_SCHEMA.md Section 3.17
DEFAULT_ABBREVIATION_DICTIONARY = {
    "MT": "metric_ton",
    "KG": "kilogram",
    "KGS": "kilogram",
    "GM": "gram",
    "GMS": "gram",
    "NOS": "nos",
    "NO": "nos",
    "PCS": "nos",
    "PC": "nos",
    "BOX": "box",
    "BX": "box",
    "SET": "set",
    "SQFT": "square_foot",
    "SFT": "square_foot",
    "SQM": "square_metre",
    "RMT": "running_metre",
    "RM": "running_metre",
    "LTR": "litre",
    "LT": "litre",
    "ML": "millilitre",
    "PKT": "packet",
    "PKG": "package",
    "DZ": "dozen",
    "PR": "pair",
}


class TenantSettings(Base):
    """Per-tenant configuration. RLS-scoped by tenant_id."""

    __tablename__ = "tenant_settings"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        primary_key=True,
    )
    abbreviation_dictionary = Column(JSONB, nullable=False)
    fuzzy_threshold = Column(Float, nullable=False, server_default="0.85")
    duplicate_window_days = Column(Integer, nullable=False, server_default="30")
    manual_review_threshold = Column(Float, nullable=False, server_default="0.70")
    base_currency = Column(String(3), nullable=False, server_default="INR")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
