"""The Flag-It API. Each stage owns an APIRouter; this module only mounts them.

    uvicorn flag_it.api:app

To add a stage's routes, import its router and add one include_router line below.
"""

from fastapi import FastAPI

from flag_it.intake.routes import router as intake_router


def create_app() -> FastAPI:
    app = FastAPI(title="Flag-It")
    app.include_router(intake_router)
    return app


app = create_app()
