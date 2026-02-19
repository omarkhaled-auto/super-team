"""Data models for the authentication service."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class UserRole(Enum):
    """Roles available for users in the system."""

    ADMIN = "admin"
    USER = "user"
    MODERATOR = "moderator"


class User(BaseModel):
    """Represents a registered user account."""

    id: int
    email: str
    name: str
    role: UserRole = UserRole.USER
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True


class TokenPayload(BaseModel):
    """Payload embedded inside a JWT token."""

    user_id: int
    exp: datetime
    iat: datetime = Field(default_factory=datetime.utcnow)


class LoginRequest(BaseModel):
    """Schema for user login attempts."""

    email: str
    password: str


class LoginResponse(BaseModel):
    """Schema returned after a successful login."""

    access_token: str
    token_type: str = "bearer"
    user: User


class UserCreate(BaseModel):
    """Schema for creating a new user account."""

    email: str
    password: str
    name: str
    role: Optional[UserRole] = UserRole.USER


def validate_email(email: str) -> bool:
    """Check that an email address contains an @ symbol and a domain."""
    return "@" in email and "." in email.split("@")[-1]


def validate_password(password: str) -> bool:
    """Ensure the password meets minimum security requirements."""
    return len(password) >= 8
