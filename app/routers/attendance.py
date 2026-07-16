import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole
from app.models.course import Course
from app.models.class_session import ClassSession
from app.models.attendance import AttendanceRecord, AttendanceStatus
from app.models.active_token import ActiveToken

from app.schemas import (
    SessionCreate,
    SessionResponse,
    TokenResponse,
    CheckInRequest,
    AttendanceResponse,
)
from app.utils.geo import calculate_haversine_distance
from app.utils.security import create_session_jwt, decode_session_jwt, hash_token

router = APIRouter(prefix="/api/v1", tags=["attendance"])


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initialize a new class session",
)
async def create_session(
    payload: SessionCreate,
    db: Session = Depends(get_db)
):
    """
    Allows lecturers to initialize a new class session with target GPS coordinates
    and allowed geofencing radius.
    """
    # Verify course exists
    course = db.query(Course).filter(Course.id == payload.course_id).first()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course with ID {payload.course_id} does not exist"
        )

    # Instantiate class session
    new_session = ClassSession(
        course_id=payload.course_id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        latitude=payload.latitude,
        longitude=payload.longitude,
        allowed_radius_meters=payload.allowed_radius_meters,
    )
    
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return new_session


@router.get(
    "/sessions/{session_id}/token",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate dynamic session token",
)
async def get_session_token(
    session_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Generates a dynamic signature-verified JWT containing the session ID
    with a precise 15-second expiration, storing the token signature hash database-side.
    """
    # Verify class session exists
    session_record = db.query(ClassSession).filter(ClassSession.id == session_id).first()
    if not session_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Class session with ID {session_id} not found"
        )

    # Ensure the session is currently active/ongoing
    now = datetime.datetime.now(datetime.timezone.utc)
    if now > session_record.end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot generate token. Class session has already ended"
        )

    # Generate the JWT
    token_str, expires_at = create_session_jwt(session_id)
    token_signature_hash = hash_token(token_str)

    # Save active token to database to ensure validity tracking
    active_token = ActiveToken(
        session_id=session_id,
        token_hash=token_signature_hash,
        expires_at=expires_at,
    )
    db.add(active_token)
    db.commit()

    return TokenResponse(token=token_str, expires_at=expires_at)


@router.post(
    "/attendance/submit",
    response_model=AttendanceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit student attendance check-in",
)
async def submit_attendance(
    payload: CheckInRequest,
    db: Session = Depends(get_db)
):
    """
    Allows students to check-in. Validates the dynamic token, expiration,
    computes geo-fence limits, and verifies device constraints.
    """
    # 1. JWT Signature decoding and expiration validation
    session_id = decode_session_jwt(payload.token)

    # 2. Database active token tracking check (prevents replay attacks/forgery)
    token_signature_hash = hash_token(payload.token)
    active_token = db.query(ActiveToken).filter(
        ActiveToken.token_hash == token_signature_hash,
        ActiveToken.session_id == session_id
    ).first()

    if not active_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token is inactive, invalid, or has already been used"
        )

    # Check database-side expiration
    now = datetime.datetime.now(datetime.timezone.utc)
    if now > active_token.expires_at:
        db.delete(active_token)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has expired database-side"
        )

    # 3. Retrieve Class Session and Student user records
    session_record = db.query(ClassSession).filter(ClassSession.id == session_id).first()
    if not session_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated class session not found"
        )

    # Verify student exists and holds student role
    student = db.query(User).filter(
        User.id == payload.student_id,
    ).first()
    
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student user record not found"
        )
    if student.role != UserRole.STUDENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only registered students can check-in to class sessions"
        )

    # 4. Pure mathematical implementation of the Haversine formula
    distance_meters = calculate_haversine_distance(
        lat1=session_record.latitude,
        lon1=session_record.longitude,
        lat2=payload.student_latitude,
        lon2=payload.student_longitude,
    )

    if distance_meters > session_record.allowed_radius_meters:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Location verification failed. Student is outside the allowed geofence. "
                f"Distance: {distance_meters:.2f}m. Maximum allowed: {session_record.allowed_radius_meters}m"
            )
        )

    # 5. Database constraint check: unique student submission per session
    existing_student_record = db.query(AttendanceRecord).filter(
        AttendanceRecord.session_id == session_id,
        AttendanceRecord.student_id == payload.student_id
    ).first()
    
    if existing_student_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attendance already submitted for this student in this session"
        )

    # 6. Database constraint check: unique submission per device per session
    existing_device_record = db.query(AttendanceRecord).filter(
        AttendanceRecord.session_id == session_id,
        AttendanceRecord.device_hash == payload.device_hash
    ).first()

    if existing_device_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attendance already submitted using this device in this session"
        )

    # Determine attendance status based on session timing (e.g. late if past start time)
    # Default to present for generic valid submissions, or compare current time to session parameters
    session_start_naive = session_record.start_time.replace(tzinfo=None)
    status_now = AttendanceStatus.PRESENT
    # If the student checks in 10 minutes or more past the session start, classify as LATE
    check_in_time_naive = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    if check_in_time_naive > session_start_naive + datetime.timedelta(minutes=10):
        status_now = AttendanceStatus.LATE

    # Create the attendance record
    attendance_record = AttendanceRecord(
        student_id=payload.student_id,
        session_id=session_id,
        status=status_now,
        device_hash=payload.device_hash,
        student_latitude=payload.student_latitude,
        student_longitude=payload.student_longitude,
    )

    db.add(attendance_record)
    
    # Clean up token database-side to prevent any form of token replay/re-use
    db.delete(active_token)
    
    db.commit()
    db.refresh(attendance_record)

    return attendance_record


@router.get(
    "/sessions/{session_id}/attendance",
    response_model=list[AttendanceResponse],
    status_code=status.HTTP_200_OK,
    summary="Get attendance records for a class session",
)
async def get_session_attendance(
    session_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Returns a list of all successful student attendance records for the specified class session.
    """
    # Verify class session exists
    session_record = db.query(ClassSession).filter(ClassSession.id == session_id).first()
    if not session_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Class session with ID {session_id} not found"
        )
    
    # Query attendance records
    records = db.query(AttendanceRecord).filter(
        AttendanceRecord.session_id == session_id
    ).order_by(AttendanceRecord.timestamp.desc()).all()
    
    return records

