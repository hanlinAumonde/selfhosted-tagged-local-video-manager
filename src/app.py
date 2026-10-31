from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import asynccontextmanager
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from strawberry.fastapi import GraphQLRouter
from strawberry.subscriptions import GRAPHQL_TRANSPORT_WS_PROTOCOL, GRAPHQL_WS_PROTOCOL
from src.config import init_settings
from src.schema.strawberry_schema import schema
from src.context import get_cache_service, get_context, init_task_runner
from src.db.setup_mongo import setup_mongo
from src.logger import get_logger, setup_logger
from src.features.playback import video_router

logger = get_logger("app")

async def global_exception_handler(request: Request, exc: HTTPException):
    logger.exception(
        f"Unhandled exception: {exc.status_code} - {exc.detail}"
        f" on path: {request.url.path}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

def create_app():
    settings = init_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logger(
            log_dir=settings.logging.log_dir,
            rotation=settings.logging.rotation,
            retention=settings.logging.retention,
        )
        await setup_mongo(settings.mongo)
        task_runner = await init_task_runner()
        yield
        await task_runner.shutdown()
        await get_cache_service(settings).close()
        logger.info("Application shutdown")

    app = FastAPI(lifespan=lifespan)

    app.add_exception_handler(HTTPException, global_exception_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    graphql_app = GraphQLRouter(
        schema,
        subscription_protocols=[
            GRAPHQL_TRANSPORT_WS_PROTOCOL,
            GRAPHQL_WS_PROTOCOL,
        ],
        context_getter=get_context,
    )
    app.include_router(graphql_app, prefix="/graphql")
    app.include_router(video_router.router)


    logger.info("Application startup complete")

    return app
