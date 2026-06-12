from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.utils import load_session_secret, PROJECT_ROOT
from backend.routers import auth, student, teacher

app = FastAPI(title="SnapClass", docs_url=None, redoc_url=None)

app.add_middleware(
    SessionMiddleware,
    secret_key=load_session_secret(),
    same_site="lax",
    max_age=60 * 60 * 24 * 14,  # 2 weeks
)

app.include_router(auth.router)
app.include_router(student.router)
app.include_router(teacher.router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/join/{code}")
def join_redirect(code: str):
    #QR codes land here; student page handles the rest
    return RedirectResponse(f"/student.html?join-code={code}")


@app.get("/attend")
def attend_redirect(t: str):
    #live QR attendance codes land here; survives the login flow as ?attend=
    return RedirectResponse(f"/student.html?attend={t}")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server."})


WEB_DIR = PROJECT_ROOT / "web"
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
