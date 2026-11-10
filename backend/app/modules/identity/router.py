from fastapi import APIRouter, Request, Response

from app.core.errors import AppError
from app.modules.identity import service
from app.modules.identity.deps import CurrentUser, SessionDep
from app.modules.identity.schemas import LoginIn, RegisterIn, UserOut
from app.shared.ratelimit import login_limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
async def register(body: RegisterIn, request: Request, session: SessionDep):
    user = await service.register(session, body.email, body.password, body.display_name)
    request.session["user_id"] = user.id
    return user


@router.post("/login", response_model=UserOut)
async def login(body: LoginIn, request: Request, session: SessionDep):
    ip = request.client.host if request.client else "unknown"
    if not login_limiter.hit(ip):
        raise AppError(429, "rate_limited", "Too many login attempts. Try again in a minute.")
    user = await service.authenticate(session, body.email, body.password)
    request.session["user_id"] = user.id
    return user


@router.post("/logout", status_code=204)
async def logout(request: Request):
    request.session.clear()
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user
