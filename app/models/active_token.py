import datetime
import uuid
from typing import TYPE_CHECKING
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.class_session import ClassSession


class ActiveToken(Base):
    """
    ActiveToken model representing temporary dynamic tokens (e.g., dynamically changing QR codes)
    associated with class sessions.
    Used for verifying attendance authenticity.
    """
    __tablename__ = "active_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique identifier for the active token"
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("class_sessions.id", ondelete="CASCADE"),
        nullable=False,
        doc="Foreign key referencing the associated ClassSession"
    )
    token_hash: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
        doc="Hashed token value used for verification"
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Expiration timestamp of the token"
    )

    # Bidirectional relationships
    session: Mapped["ClassSession"] = relationship(
        "ClassSession",
        back_populates="active_tokens",
        doc="The session for which this token is valid"
    )
