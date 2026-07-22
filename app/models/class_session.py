import datetime
import uuid
from typing import List, TYPE_CHECKING
from sqlalchemy import DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.attendance import AttendanceRecord
    from app.models.active_token import ActiveToken


class ClassSession(Base):
    """
    ClassSession model representing individual scheduled lectures/sessions for a course.
    Includes geofencing metadata to restrict attendance submissions.
    """
    __tablename__ = "class_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique identifier for the class session"
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        doc="Foreign key referencing the course this session belongs to"
    )
    start_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Scheduled start time of the class session"
    )
    end_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Scheduled end time of the class session"
    )
    latitude: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Latitude coordinate of the classroom geofence center"
    )
    longitude: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Longitude coordinate of the classroom geofence center"
    )
    allowed_radius_meters: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Radius in meters from classroom coordinates where student is allowed to mark attendance"
    )
    grace_period_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=10,
        doc="Minutes after start_time when a student is still marked PRESENT"
    )
    late_period_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        doc="Minutes after start_time when a student is marked LATE. Beyond this, check-in is closed."
    )

    # Bidirectional relationships
    course: Mapped["Course"] = relationship(
        "Course",
        back_populates="sessions",
        doc="The parent course for this session"
    )
    attendance_records: Mapped[List["AttendanceRecord"]] = relationship(
        "AttendanceRecord",
        back_populates="session",
        cascade="all, delete-orphan",
        doc="List of student attendance records for this session"
    )
    active_tokens: Mapped[List["ActiveToken"]] = relationship(
        "ActiveToken",
        back_populates="session",
        cascade="all, delete-orphan",
        doc="List of dynamic tokens active during this session"
    )
