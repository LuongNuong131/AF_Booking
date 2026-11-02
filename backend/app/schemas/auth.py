from typing import Literal

from pydantic import Field, JsonValue, SecretStr

from app.schemas.contracts import ContractModel

UserRole = Literal["admin", "qc", "agent"]


class LoginRequest(ContractModel):
    username: str = Field(min_length=1, max_length=50)
    password: SecretStr = Field(min_length=1, max_length=1024)


class ChangePasswordRequest(ContractModel):
    old_password: SecretStr = Field(min_length=1, max_length=1024)
    new_password: SecretStr = Field(min_length=12, max_length=1024)


class PublicUser(ContractModel):
    id: int
    username: str
    full_name: str
    role: UserRole
    is_active: bool
    settings: dict[str, JsonValue] | None


class LoginResponse(ContractModel):
    access_token: str
    user: PublicUser
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class MessageResponse(ContractModel):
    message: str


AUTH_MODELS = (LoginRequest, ChangePasswordRequest, PublicUser, LoginResponse, MessageResponse)
