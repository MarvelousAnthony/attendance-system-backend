import datetime
import hashlib
import random
import sys
import uuid
from sqlalchemy.orm import Session

# Ensure the app package path is in the search path
sys.path.insert(0, ".")

from app.database import engine, SessionLocal
from app.models.base import Base
from app.models.user import User, UserRole
from app.models.course import Course
from app.models.class_session import ClassSession
from app.models.attendance import AttendanceRecord, AttendanceStatus


def clear_database():
    """
    Clears all existing transactional records to guarantee a clean slate.
    Performs drop and recreate on the database metadata.
    """
    print("WARNING: Clearing all tables to guarantee a clean seed slate...")
    try:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        print("Database schema dropped and recreated successfully.")
    except Exception as e:
        print(f"Error resetting database: {e}")
        sys.exit(1)


def seed_database(db: Session):
    """
    Generates structured mock data for local testing.
    - 1 Lecturer
    - 3 Courses
    - 15 Students
    - 4 Weeks of weekly ClassSessions and corresponding AttendanceRecords
    """
    print("\nStarting Seeding Routine...")

    # 1. Seed Lecturer
    lecturer = User(
        name="Dr. Elizabeth Vance",
        email="e.vance@university.edu",
        hashed_password="hashed_lecturer_password_vance123",
        role=UserRole.LECTURER,
    )
    db.add(lecturer)
    db.commit()
    db.refresh(lecturer)
    print(f"✓ Seeded Lecturer: {lecturer.name} (Email: {lecturer.email})")

    # 2. Seed 3 Courses
    courses = [
        Course(
            course_code="CSE-402",
            course_title="Distributed Systems & Cloud Computing",
            lecturer_id=lecturer.id,
            department="Computer Engineering",
        ),
        Course(
            course_code="CSE-408",
            course_title="Artificial Intelligence & Robotics",
            lecturer_id=lecturer.id,
            department="Computer Engineering",
        ),
        Course(
            course_code="CSE-301",
            course_title="Database Management Systems",
            lecturer_id=lecturer.id,
            department="Computer Science",
        ),
    ]
    db.add_all(courses)
    db.commit()
    for course in courses:
        db.refresh(course)
        print(f"✓ Seeded Course: {course.course_code} - {course.course_title}")

    # 3. Seed 15 Students
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
    print(f"✓ Seeded {len(students)} Student user profiles.")

    # 4. Seed 4 Weeks of Historical Attendance
    # Establish a campus GPS coordinate center (San Francisco coordinate example)
    campus_latitude = 37.774929
    campus_longitude = -122.419416
    allowed_radius = 50  # meters

    now = datetime.datetime.now(datetime.timezone.utc)
    attendance_records_created = 0

    print("\nGenerating historical sessions and check-ins...")
    
    # Generate weekly sessions for each of the past 4 weeks
    for week in range(4):
        weeks_ago = 4 - week
        
        for course_idx, course in enumerate(courses):
            # Formulate the historical schedule day
            session_date = now - datetime.timedelta(weeks=weeks_ago)
            # Offset hours depending on the course to avoid overlaps
            session_start = session_date.replace(
                hour=9 + course_idx * 2, minute=0, second=0, microsecond=0
            )
            session_end = session_start + datetime.timedelta(hours=1, minutes=30)

            # Insert ClassSession
            session = ClassSession(
                course_id=course.id,
                start_time=session_start,
                end_time=session_end,
                latitude=campus_latitude,
                longitude=campus_longitude,
                allowed_radius_meters=allowed_radius,
                grace_period_minutes=10,
                late_period_minutes=30,
            )
            db.add(session)
            db.commit()
            db.refresh(session)

            # Seed attendance checks for all 15 students for this session
            for student in students:
                rand = random.random()
                
                # ~80% Present check-ins (Inside Geofence, checked in early/on-time)
                if rand < 0.80:
                    status = AttendanceStatus.PRESENT
                    check_in_offset = random.uniform(-5, 9)  # minutes relative to start
                    
                    # Offset within allowed geofence (~10 to 35 meters away)
                    lat_offset = random.uniform(-0.0002, 0.0002)
                    lon_offset = random.uniform(-0.0002, 0.0002)
                    
                # ~13% Late check-ins (Inside Geofence, checked in 11 to 25 mins late)
                elif rand < 0.93:
                    status = AttendanceStatus.LATE
                    check_in_offset = random.uniform(11, 25)
                    
                    lat_offset = random.uniform(-0.0002, 0.0002)
                    lon_offset = random.uniform(-0.0002, 0.0002)
                    
                # ~7% Absent check-ins (Outside Geofence, coordinates located far away)
                else:
                    status = AttendanceStatus.ABSENT
                    check_in_offset = random.uniform(-5, 45)
                    
                    # Offset outside geofence bounds (~300 to 500 meters away)
                    lat_offset = random.uniform(0.002, 0.004) * random.choice([-1, 1])
                    lon_offset = random.uniform(0.002, 0.004) * random.choice([-1, 1])

                check_in_time = session_start + datetime.timedelta(minutes=check_in_offset)
                
                # Derive a consistent mock device fingerprint signature
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
                attendance_records_created += 1

            db.commit()

    print(f"✓ Created 12 class sessions with {attendance_records_created} check-in logs.")


def main():
    # 1. Recreate tables
    clear_database()

    # 2. Seed mock records
    db = SessionLocal()
    try:
        seed_database(db)
        print("\nSUCCESS: Local development database seeding finished successfully!")
    except Exception as e:
        print(f"\nFATAL: Seeding routine crashed: {e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
