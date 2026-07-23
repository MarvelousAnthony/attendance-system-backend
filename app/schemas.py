import datetime
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, ConfigDict

# Import the enums for validation
from app.models.user import UserRole
from app.models.attendance import AttendanceStatus


class SessionCreate(BaseModel):
    """
    Schema for creating a new class session.
    """
    course_id: UUID
    start_time: datetime.datetime
    end_time: datetime.datetime
    latitude: float = Field(..., description="Latitude coordinate of classroom center")
    longitude: float = Field(..., description="Longitude coordinate of classroom center")
    allowed_radius_meters: int = Field(..., description="Geofence boundary radius")
    grace_period_minutes: int = Field(10, description="Grace period in minutes for PRESENT status")
    late_period_minutes: int = Field(30, description="Lateness threshold in minutes for LATE status")
    require_double_signing: bool = Field(False, description="Flag indicating if check-out is required")

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        if not -90.0 <= v <= 90.0:
            raise ValueError("Latitude must be between -90 and 90 degrees")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        if not -180.0 <= v <= 180.0:
            raise ValueError("Longitude must be between -180 and 180 degrees")
        return v

    @field_validator("allowed_radius_meters")
    @classmethod
    def validate_radius(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Allowed radius must be a positive integer greater than zero")
        return v

    @field_validator("grace_period_minutes")
    @classmethod
    def validate_grace_period(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Grace period must be a positive integer greater than zero")
        return v

    @field_validator("late_period_minutes")
    @classmethod
    def validate_late_period(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Late period must be a positive integer greater than zero")
        return v

    @field_validator("late_period_minutes")
    @classmethod
    def validate_time_thresholds(cls, v: int, info) -> int:
        grace = info.data.get("grace_period_minutes")
        if grace and v <= grace:
            raise ValueError("late_period_minutes must be strictly greater than grace_period_minutes")
        return v

    @field_validator("end_time")
    @classmethod
    def validate_time_range(cls, v: datetime.datetime, info) -> datetime.datetime:
        start = info.data.get("start_time")
        if start and v <= start:
            raise ValueError("end_time must be strictly after start_time")
        return v


class SessionResponse(BaseModel):
    """
    Response schema returning details of a class session.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    course_id: UUID
    start_time: datetime.datetime
    end_time: datetime.datetime
    latitude: float
    longitude: float
    allowed_radius_meters: int
    grace_period_minutes: int
    late_period_minutes: int
    require_double_signing: bool
    is_checkout_open: bool


class TokenResponse(BaseModel):
    """
    Response schema returning dynamic JWT token.
    """
    token: str
    expires_at: datetime.datetime


class CheckInRequest(BaseModel):
    """
    Schema for student attendance check-in request.
    """
    token: str = Field(..., description="Dynamic verification JWT token")
    student_id: UUID = Field(..., description="UUID of the student")
    student_latitude: float = Field(..., description="Student current latitude GPS coordinate")
    student_longitude: float = Field(..., description="Student current longitude GPS coordinate")
    device_hash: str = Field(..., description="Browser or device hardware fingerprint")

    @field_validator("student_latitude")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        if not -90.0 <= v <= 90.0:
            raise ValueError("Latitude must be between -90 and 90 degrees")
        return v

    @field_validator("student_longitude")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        if not -180.0 <= v <= 180.0:
            raise ValueError("Longitude must be between -180 and 180 degrees")
        return v


class AttendanceResponse(BaseModel):
    """
    Response schema returning student attendance record details.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    session_id: UUID
    timestamp: datetime.datetime
    checked_out_at: datetime.datetime | None
    status: AttendanceStatus
    device_hash: str
    student_latitude: float
    student_longitude: float


class StudentOnboardRequest(BaseModel):
    name: str = Field(..., description="Student full name")
    email: str = Field(..., description="Student email address")
    student_id: str = Field(..., description="Student matric number (e.g. 23/0987)")
    department: str = Field(..., description="Student department name")
    face_encoding: str = Field(..., description="Serialized JSON array of facial encoding vector")


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    role: str
    student_id: str | None = None
    face_encoding: str | None = None
