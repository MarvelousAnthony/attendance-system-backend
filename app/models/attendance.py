import datetime
import enum
import uuid
from typing import TYPE_CHECKING
from sqlalchemy import DateTime, Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.class_session import ClassSession


class AttendanceStatus(str, enum.Enum):
    """
    Possible states for a student's attendance record.
    """
    PRESENT = "present"
    LATE = "late"
    ABSENT = "absent"


class AttendanceRecord(Base):
    """
    AttendanceRecord model representing student attendance submissions for individual sessions.
    Captures verification criteria like device finger-print and geolocation coordinates.
    """
    __tablename__ = "attendance_records"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique identifier for the attendance record"
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        doc="Foreign key referencing the student (User)"
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("class_sessions.id", ondelete="CASCADE"),
        nullable=False,
        doc="Foreign key referencing the ClassSession"
    )
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        nullable=False,
        doc="Time when attendance was marked"
    )
    status: Mapped[AttendanceStatus] = mapped_column(
        Enum(AttendanceStatus),
        nullable=False,
        doc="Attendance status (present, late, or absent)"
    )
    device_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Hash representing the student's hardware device signature for integrity check"
    )
    student_latitude: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Latitude coordinate reported by student's device"
    )
    student_longitude: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Longitude coordinate reported by student's device"
    )

    # Bidirectional relationships
    student: Mapped["User"] = relationship(
        "User",
        back_populates="attendance_records",
        doc="The student associated with this attendance record"
    )
    session: Mapped["ClassSession"] = relationship(
        "ClassSession",
        back_populates="attendance_records",
        doc="The session associated with this attendance record"
    )
