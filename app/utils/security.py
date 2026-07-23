import datetime
import hashlib
import os
import uuid
import jwt
from fastapi import HTTPException, status

# Load Secret Key from environment, with a secure fallback for development
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "prod_grade_attendance_jwt_verification_secret_key_change_me_in_production")
ALGORITHM = "HS256"


def hash_token(token: str) -> str:
    """
    Computes a SHA-256 hash of the token string.
    Ensures safe storage and fast indexing of active tokens.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session_jwt(session_id: uuid.UUID, is_checkout: bool = False) -> tuple[str, datetime.datetime]:
    """
    Generates a dynamic JWT containing the session ID and a precise 15-second expiration.
    Returns the encoded JWT token and its expiration timestamp.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = now + datetime.timedelta(seconds=15)
    
    payload = {
        "session_id": str(session_id),
        "is_checkout": is_checkout,
        "iat": now,
        "exp": expires_at
    }
    
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token, expires_at


def decode_session_jwt(token: str) -> tuple[uuid.UUID, bool]:
    """
    Decodes and validates the signature and expiration of a session JWT.
    
    Raises 401 Unauthorized exceptions if the token has expired, has an invalid signature,
    or contains malformed data.
    """
    try:
        # Decode checks exp expiration internally
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        session_id_str = payload.get("session_id")
        is_checkout = payload.get("is_checkout", False)
        
        if not session_id_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload is missing session_id"
            )
            
        return uuid.UUID(session_id_str), is_checkout
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token"
        )
