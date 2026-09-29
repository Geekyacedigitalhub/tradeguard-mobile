from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from .auth import hash_password, verify_password, create_token
from .db import connection

router = APIRouter(prefix="/v1/auth", tags=["auth"])

class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = None

class LoginRequest(BaseModel):
    email: str
    password: str

@router.post("/register")
def register(body: RegisterRequest):
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "Enter a valid email")
    with connection() as conn:
        try:
            row = conn.execute(
                "INSERT INTO users (email, password_hash, display_name) VALUES (%s,%s,%s) RETURNING id, email, display_name",
                (email, hash_password(body.password), body.display_name)
            ).fetchone()
            user_id = str(row[0])
            conn.execute("INSERT INTO account_state (user_id) VALUES (%s)", (user_id,))
            conn.execute("INSERT INTO bot_state (user_id) VALUES (%s)", (user_id,))
        except Exception as exc:
            if "duplicate key" in str(exc).lower():
                raise HTTPException(409, "An account with this email already exists")
            raise
    return {"token": create_token(user_id), "user": {"id": user_id, "email": row[1], "display_name": row[2]}}

@router.post("/login")
def login(body: LoginRequest):
    email = body.email.strip().lower()
    with connection() as conn:
        row = conn.execute("SELECT id, email, display_name, password_hash FROM users WHERE email=%s", (email,)).fetchone()
    if not row or not verify_password(body.password, row[3]):
        raise HTTPException(401, "Invalid email or password")
    user_id = str(row[0])
    return {"token": create_token(user_id), "user": {"id": user_id, "email": row[1], "display_name": row[2]}}

@router.get("/me")
def me(user=__import__("fastapi").Depends(__import__("backend.app.auth", fromlist=["current_user"]).current_user)):
    return {"user": user}
