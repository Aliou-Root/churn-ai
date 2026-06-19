"""
ORM models for ChurnAI — users, usage events, churn scores, action logs.

v2: ActionTypeEnum étendu avec no_action et flag_for_review
    (valeurs retournées par le CEO Agent Claude).
"""

import enum
import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.database import Base


class ActionTypeEnum(str, enum.Enum):
    email         = "email"
    discount      = "discount"
    notification  = "notification"
    call          = "call"
    upgrade_offer = "upgrade_offer"
    # Ajoutés v2 — valeurs possibles du CEO Agent Claude
    no_action     = "no_action"       # client pas réellement à risque
    flag_for_review = "flag_for_review"  # cas ambigu → revue manuelle CSM


class RiskLevelEnum(str, enum.Enum):
    low      = "low"
    medium   = "medium"
    high     = "high"
    critical = "critical"


# ─── User / Subscriber ────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email              = Column(String(255), unique=True, nullable=False, index=True)
    name               = Column(String(255))
    company            = Column(String(255))
    plan               = Column(String(50), default="starter")
    mrr                = Column(Float, default=0.0)
    stripe_customer_id = Column(String(100), index=True)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at       = Column(DateTime(timezone=True))
    is_active          = Column(Boolean, default=True)

    usage_events = relationship("UsageEvent", back_populates="user")
    churn_scores = relationship("ChurnScore",  back_populates="user")
    action_logs  = relationship("ActionLog",   back_populates="user")


# ─── Usage Events ─────────────────────────────────────────────────────────────

class UsageEvent(Base):
    __tablename__ = "usage_events"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    event_type  = Column(String(100), nullable=False)
    feature     = Column(String(100))
    extra_data  = Column(JSON, default={})   # renommé depuis 'metadata' (réservé par SQLAlchemy)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="usage_events")


# ─── Churn Score ──────────────────────────────────────────────────────────────

class ChurnScore(Base):
    __tablename__ = "churn_scores"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id              = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    score                = Column(Float, nullable=False)
    risk_level           = Column(Enum(RiskLevelEnum), nullable=False)
    factors              = Column(JSON, default={})
    predicted_churn_date = Column(DateTime(timezone=True))
    revenue_at_risk      = Column(Float, default=0.0)
    created_at           = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="churn_scores")


# ─── Action Log ───────────────────────────────────────────────────────────────

class ActionLog(Base):
    __tablename__ = "action_logs"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    action_type   = Column(Enum(ActionTypeEnum), nullable=False)
    payload       = Column(JSON, default={})
    executed_at   = Column(DateTime(timezone=True), server_default=func.now())
    success       = Column(Boolean, default=True)
    revenue_saved = Column(Float, default=0.0)
    # v2 — CEO Agent metadata
    ceo_override  = Column(Boolean, default=False)   # action modifiée par CEO Agent
    claude_personalized = Column(Boolean, default=False)  # email généré par l'IA
    # v5 — feedback loop: did the action actually prevent churn?
    retained            = Column(Boolean)                 # None = pending, True/False = recorded
    actual_revenue_saved = Column(Float)                  # measured, vs. estimated revenue_saved
    outcome_recorded_at = Column(DateTime(timezone=True))

    user = relationship("User", back_populates="action_logs")


# ─── Pipeline Run (time-series snapshots) ──────────────────────────────────────

class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at        = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    users_at_risk     = Column(Integer, default=0)
    revenue_at_risk   = Column(Float, default=0.0)
    revenue_saved     = Column(Float, default=0.0)
    roi_ratio         = Column(Float, default=0.0)
    avg_churn_score   = Column(Float, default=0.0)
    success_rate      = Column(Float, default=0.0)
    actions_executed  = Column(Integer, default=0)
    duration_seconds  = Column(Float, default=0.0)
    ai_used           = Column(Boolean, default=False)
