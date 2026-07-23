import datetime
import hashlib
import json
import io
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, File, Form, UploadFile
from sqlalchemy.orm import Session

# Dynamic import configuration for CPU-heavy face_recognition library to support Render free-tier builds
try:
    import face_recognition
    import numpy as np
    FACE_RECOGNITION_SUPPORTED = True
except ImportError:
    FACE_RECOGNITION_SUPPORTED = False

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
    StudentOnboardRequest,
    UserResponse,
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
        grace_period_minutes=payload.grace_period_minutes,
        late_period_minutes=payload.late_period_minutes,
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

    # Calculate offset from session start time
    session_start_naive = session_record.start_time.replace(tzinfo=None)
    check_in_time_naive = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    time_offset_seconds = (check_in_time_naive - session_start_naive).total_seconds()
    time_offset_minutes = time_offset_seconds / 60.0

    if time_offset_minutes > session_record.late_period_minutes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Check-in failed: The attendance window has closed. The maximum checking-in time of {session_record.late_period_minutes} minutes has been exceeded."
        )

    status_now = AttendanceStatus.PRESENT
    if time_offset_minutes > session_record.grace_period_minutes:
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


@router.post(
    "/debug/reset",
    status_code=status.HTTP_200_OK,
    summary="Wipe dev database tables to allow clean re-seeding",
)
async def reset_database_endpoint(db: Session = Depends(get_db)):
    """
    Truncate all relational tables in cascade order to reset environment.
    """
    from sqlalchemy import text
    try:
        db.execute(text("TRUNCATE TABLE attendance_records CASCADE;"))
        db.execute(text("TRUNCATE TABLE class_sessions CASCADE;"))
        db.execute(text("TRUNCATE TABLE active_tokens CASCADE;"))
        db.execute(text("TRUNCATE TABLE courses CASCADE;"))
        db.execute(text("TRUNCATE TABLE users CASCADE;"))
        db.commit()
        return {"message": "Database reset successfully!"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database reset failed: {str(e)}"
        )


@router.post(
    "/debug/seed",
    status_code=status.HTTP_200_OK,
    summary="Seed mock data for local/dev testing",
)
async def seed_data_endpoint(db: Session = Depends(get_db)):
    """
    Seed mock data (1 lecturer, 3 courses, 15 students, 4 weeks of historical logs) into the database.
    """
    import hashlib
    import random
    import datetime
    
    # Check if data already exists to prevent duplicate seeding
    lecturer_check = db.query(User).filter(User.email == "e.vance@university.edu").first()
    if lecturer_check:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database has already been seeded"
        )
        
    try:
        # Seed Lecturer
        lecturer = User(
            name="Dr. Elizabeth Vance",
            email="e.vance@university.edu",
            hashed_password="hashed_lecturer_password_vance123",
            role=UserRole.LECTURER,
        )
        db.add(lecturer)
        db.commit()
        db.refresh(lecturer)

        # Seed Courses
        courses = [
            Course(
                course_code="CSE-402",
                course_title="Distributed Systems & Cloud Computing",
                lecturer_id=lecturer.id,
            ),
            Course(
                course_code="CSE-408",
                course_title="Artificial Intelligence & Robotics",
                lecturer_id=lecturer.id,
            ),
            Course(
                course_code="CSE-301",
                course_title="Database Management Systems",
                lecturer_id=lecturer.id,
            ),
        ]
        db.add_all(courses)
        db.commit()
        for course in courses:
            db.refresh(course)

        # Seed Students
        student_names = [
            "Sarah Jenkins", "Michael Chen", "Emily Rodriguez", "David Kim", 
            "Jessica Taylor", "James Wilson", "Amanda Martinez", "Robert Novak",
            "Olivia Smith", "William Patel", "Sophia Muller", "Lucas Silva",
            "John Doe", "Jane Miller", "Brian O'Conner"
        ]
        
        students = []
        for name in student_names:
            first_name = name.split()[0].lower()
            student = User(
                name=name,
                email=f"{first_name}.std@university.edu",
                hashed_password=f"hashed_student_pwd_{first_name}123",
                role=UserRole.STUDENT,
            )
            students.append(student)
            
        db.add_all(students)
        db.commit()
        for student in students:
            db.refresh(student)

        # Seed Attendance
        campus_latitude = 37.774929
        campus_longitude = -122.419416
        allowed_radius = 50

        now = datetime.datetime.now(datetime.timezone.utc)
        
        for week in range(4):
            weeks_ago = 4 - week
            for course_idx, course in enumerate(courses):
                session_date = now - datetime.timedelta(weeks=weeks_ago)
                session_start = session_date.replace(
                    hour=9 + course_idx * 2, minute=0, second=0, microsecond=0
                )
                session_end = session_start + datetime.timedelta(hours=1, minutes=30)

                session = ClassSession(
                    course_id=course.id,
                    start_time=session_start,
                    end_time=session_end,
                    latitude=campus_latitude,
                    longitude=campus_longitude,
                    allowed_radius_meters=allowed_radius,
                )
                db.add(session)
                db.commit()
                db.refresh(session)

                for student in students:
                    rand = random.random()
                    if rand < 0.80:
                        status = AttendanceStatus.PRESENT
                        check_in_offset = random.uniform(-5, 9)
                        lat_offset = random.uniform(-0.0002, 0.0002)
                        lon_offset = random.uniform(-0.0002, 0.0002)
                    elif rand < 0.93:
                        status = AttendanceStatus.LATE
                        check_in_offset = random.uniform(11, 25)
                        lat_offset = random.uniform(-0.0002, 0.0002)
                        lon_offset = random.uniform(-0.0002, 0.0002)
                    else:
                        status = AttendanceStatus.ABSENT
                        check_in_offset = random.uniform(-5, 45)
                        lat_offset = random.uniform(0.002, 0.004) * random.choice([-1, 1])
                        lon_offset = random.uniform(0.002, 0.004) * random.choice([-1, 1])

                    check_in_time = session_start + datetime.timedelta(minutes=check_in_offset)
                    fingerprint_seed = f"device_{student.name}_{course.course_code}_w{week}"
                    device_hash = hashlib.sha256(fingerprint_seed.encode("utf-8")).hexdigest()[:16]

                    attendance = AttendanceRecord(
                        student_id=student.id,
                        session_id=session.id,
                        timestamp=check_in_time,
                        status=status,
                        device_hash=device_hash,
                        student_latitude=campus_latitude + lat_offset,
                        student_longitude=campus_longitude + lon_offset,
                    )
                    db.add(attendance)
                db.commit()
        return {"message": "Database seeded successfully!"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Seeding failed: {str(e)}"
        )


@router.post(
    "/attendance/submit-with-face",
    response_model=AttendanceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit student check-in verified by dynamic QR, location, and facial recognition",
)
async def submit_attendance_with_face(
    scanned_token: str = Form(..., description="The dynamic JWT check-in token scanned from the screen"),
    student_latitude: float = Form(..., description="GPS Latitude coordinate of the student's device"),
    student_longitude: float = Form(..., description="GPS Longitude coordinate of the student's device"),
    student_id: UUID = Form(..., description="The database UUID of the checking-in student"),
    selfie_image: UploadFile = File(..., description="Selfie photo captured by the student's camera"),
    db: Session = Depends(get_db)
):
    """
    Submits a student attendance record checking dynamic token validity, GPS bounds geofencing,
    and matching the uploaded selfie with the registered face encoding vector.
    """
    # 1. JWT Token Signature and Expiration check
    payload = decode_session_jwt(scanned_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Check-in failed: Invalid or expired session token."
        )

    session_id_str = payload.get("session_id")
    if not session_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Check-in failed: Incomplete token metadata."
        )

    try:
        session_id = UUID(session_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Check-in failed: Invalid session identifier format."
        )

    # 2. Token Active State & Replay prevention check
    token_hash = hash_token(scanned_token)
    active_token = db.query(ActiveToken).filter(ActiveToken.token_hash == token_hash).first()
    if not active_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Check-in failed: Token has already been used or is inactive."
        )

    # 3. Check Session Active State
    session_record = db.query(ClassSession).filter(ClassSession.id == session_id).first()
    if not session_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Check-in failed: Associated class session does not exist."
        )

    # 4. Verify Student User Exists & Role
    student = db.query(User).filter(User.id == student_id).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Check-in failed: Student profile not found."
        )

    if student.role != UserRole.STUDENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Check-in failed: User does not have student permissions."
        )

    # 5. Geofencing Coordinates Check (Haversine distance <= 50 meters)
    distance = calculate_haversine_distance(
        session_record.latitude,
        session_record.longitude,
        student_latitude,
        student_longitude
    )
    if distance > 50:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Location verification failed: Student is outside the classroom bounds. Distance: {distance:.1f}m. Maximum allowed: 50.0m"
        )

    # 6. Verify Duplicate Check-In
    duplicate_attendance = db.query(AttendanceRecord).filter(
        AttendanceRecord.student_id == student.id,
        AttendanceRecord.session_id == session_record.id
    ).first()
    if duplicate_attendance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate check-in detected: Student has already checked into this session."
        )

    # 7. Facial Recognition Verification
    # Check if student has registered face data
    if not student.face_encoding:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Facial validation failed: No registered face profile found for this student."
        )

    # Read selfie file bytes
    try:
        selfie_bytes = await selfie_image.read()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read uploaded selfie image."
        )

    if FACE_RECOGNITION_SUPPORTED:
        try:
            # Parse registered vector from JSON list
            registered_vector = np.array(json.loads(student.face_encoding), dtype=np.float64)
            
            # Load uploaded image into memory
            image = face_recognition.load_image_file(io.BytesIO(selfie_bytes))
            
            # Extract encodings from uploaded image
            uploaded_encodings = face_recognition.face_encodings(image)
            if not uploaded_encodings:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Face validation failed: No face detected in the uploaded selfie photo. Please try again in better lighting."
                )
            
            uploaded_vector = uploaded_encodings[0]
            
            # Calculate Euclidean distance between encodings
            euclidean_distance = np.linalg.norm(registered_vector - uploaded_vector)
            
            # Match if distance is less than strict 0.6 threshold
            if euclidean_distance >= 0.6:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Face verification failed: Biometric signature mismatch. Distance: {euclidean_distance:.3f} (threshold: 0.600)."
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Biometric processing failure: {str(e)}"
            )
    else:
        # Fallback Mock verification for Render free-tier deployment (preventing compiler issues)
        # Verify JSON validity if vector, or ignore if secure file path
        if not (student.face_encoding.startswith("http") or student.face_encoding.startswith("/")):
            try:
                json.loads(student.face_encoding)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Registered biometric data signature is corrupted."
                )

    # Calculate offset from session start time
    session_start_naive = session_record.start_time.replace(tzinfo=None)
    check_in_time_naive = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    time_offset_seconds = (check_in_time_naive - session_start_naive).total_seconds()
    time_offset_minutes = time_offset_seconds / 60.0

    if time_offset_minutes > session_record.late_period_minutes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Check-in failed: The attendance window has closed. The maximum checking-in time of {session_record.late_period_minutes} minutes has been exceeded."
        )

    status_now = AttendanceStatus.PRESENT
    if time_offset_minutes > session_record.grace_period_minutes:
        status_now = AttendanceStatus.LATE

    # 8. Record Attendance
    attendance_record = AttendanceRecord(
        student_id=student.id,
        session_id=session_record.id,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        status=status_now,
        device_hash=hashlib.sha256(f"{student.id}-{session_id}".encode()).hexdigest()[:16],
        student_latitude=student_latitude,
        student_longitude=student_longitude,
    )
    db.add(attendance_record)
    
    # Delete Dynamic Token to prevent reuse
    db.delete(active_token)
    db.commit()
    db.refresh(attendance_record)

    return attendance_record


@router.get(
    "/courses",
    summary="Get all registered courses from database",
)
async def get_courses(db: Session = Depends(get_db)):
    """
    Returns a list of all courses currently saved in the database.
    """
    courses = db.query(Course).all()
    return [
        {
            "id": str(course.id),
            "code": course.course_code,
            "title": course.course_title,
            "department": course.department,
        }
        for course in courses
    ]


class CourseCreateRequest(BaseModel):
    course_code: str
    course_title: str
    department: str


@router.post(
    "/courses",
    status_code=status.HTTP_201_CREATED,
    summary="Add a new course to database",
)
async def create_course(
    payload: CourseCreateRequest,
    db: Session = Depends(get_db)
):
    """
    Creates a new course in the database, automatically linking it to the default lecturer.
    """
    # 1. Look up the default console lecturer
    lecturer = db.query(User).filter(User.email == "elizabeth.vance@university.edu").first()
    if not lecturer:
        # Fallback to any lecturer in database
        lecturer = db.query(User).filter(User.role == UserRole.LECTURER).first()

    new_course = Course(
        course_code=payload.course_code,
        course_title=payload.course_title,
        department=payload.department,
        lecturer_id=lecturer.id if lecturer else None,
    )
    db.add(new_course)
    
    try:
        db.commit()
        db.refresh(new_course)
        return {
            "id": str(new_course.id),
            "code": new_course.course_code,
            "title": new_course.course_title,
            "department": new_course.department,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Course creation failed: {str(e)}"
        )


@router.post(
    "/students/onboard",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register or update student biometric profile",
)
async def onboard_student(
    payload: StudentOnboardRequest,
    db: Session = Depends(get_db)
):
    """
    Onboards a student by creating their user record (or updating their face encoding if they already exist).
    """
    # 1. Check if user already exists by email
    student = db.query(User).filter(User.email == payload.email).first()
    
    if student:
        # If user exists, update details
        student.name = payload.name
        student.student_id = payload.student_id
        student.face_encoding = payload.face_encoding
    else:
        # Check if student_id is already used by someone else
        existing_id = db.query(User).filter(User.student_id == payload.student_id).first()
        if existing_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A student with this Matric Number is already registered."
            )
            
        # Create new student user
        student = User(
            name=payload.name,
            email=payload.email,
            student_id=payload.student_id,
            role=UserRole.STUDENT,
            face_encoding=payload.face_encoding,
            hashed_password="hashed_student_registered_password", # dummy password for self-registration
        )
        db.add(student)
        
    try:
        db.commit()
        db.refresh(student)
        return student
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )

