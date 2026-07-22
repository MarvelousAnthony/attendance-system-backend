import uuid
from typing import List, TYPE_CHECKING
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.class_session import ClassSession


class Course(Base):
    """
    Course model representing academic courses.
    """
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique identifier for the course"
    )
    course_code: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
        doc="Unique code identifier for the course (e.g., CS101)"
    )
    course_title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Official title of the course"
    )
    department: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="Computer Engineering",
        doc="Academic department offering the course"
    )
    lecturer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        doc="Foreign key referencing the user who lectures the course"
    )

    # Bidirectional relationships
    lecturer: Mapped["User"] = relationship(
        "User",
        back_populates="courses",
        doc="The lecturer assigned to this course"
    )
    sessions: Mapped[List["ClassSession"]] = relationship(
        "ClassSession",
        back_populates="course",
        cascade="all, delete-orphan",
        doc="List of class sessions scheduled for this course"
    )
