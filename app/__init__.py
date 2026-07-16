from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers.attendance import router as attendance_router

# Instantiate FastAPI application
app = FastAPI(
    title="Automated Attendance Management System API",
    description=(
        "Production-grade backend business logic for verifying attendance check-ins. "
        "Implements GPS location verification (Haversine formula), 15-second precise expiration JWTs, "
        "and duplicate submission protection."
    ),
    version="1.0.0",
)

# Configure Cross-Origin Resource Sharing (CORS)
# Required for the Vercel-hosted frontend to connect to the Render-hosted backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins in dev; restrict to your Vercel URL in production
    allow_credentials=True,
    allow_methods=["*"],  # Allows all HTTP methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all HTTP headers
)

# Attach API endpoints router
app.include_router(attendance_router)
