from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from ..config import BASE_DIR, STATIC_VERSION

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.globals["static_version"] = STATIC_VERSION


@router.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@router.get("/r/{code}")
def room_page(request: Request, code: str):
    return templates.TemplateResponse(
        request, "room.html", {"room_code": code.upper()}
    )
