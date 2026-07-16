import enum
import uuid
from typing import List, TYPE_CHECKING
from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.attendance import AttendanceRecord


class UserRole(str, enum.Enum):
    """
    Roles available to system users.
    """
    LECTURER = "lecturer"
    STUDENT = "student"


class User(Base):
    """
    User model representing lecturers and students in the system.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique identifier for the user"
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Full name of the user"
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
        doc="Unique email address used for login"
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Hashed representation of the user password"
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole),
        nullable=False,
        doc="System role (lecturer or student)"
    )
    face_encoding: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        doc="Secure S3/Cloud Storage path to the student's registered profile photo or serialized face encoding vector"
    )

    # Bidirectional relationships
    courses: Mapped[List["Course"]] = relationship(
        "Course",
        back_populates="lecturer",
        cascade="all, delete-orphan",
        doc="List of courses taught by this user (if lecturer)"
    )
    attendance_records: Mapped[List["AttendanceRecord"]] = relationship(
        "AttendanceRecord",
        back_populates="student",
        cascade="all, delete-orphan",
        doc="List of attendance records registered by this user (if student)"
    )
