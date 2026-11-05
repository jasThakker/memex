"""Application entry point."""

from fastapi import FastAPI

from app.routes import orders, users


def create_app() -> FastAPI:
    """Build the application and mount every router."""
    application = FastAPI()

    def register(router: object) -> None:
        application.include_router(router)

    register(users.router)
    register(orders.router)
    return application


def run() -> None:
    """Serve the application; the server import is deferred until needed."""
    import uvicorn

    uvicorn.run(create_app())
