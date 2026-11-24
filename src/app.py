import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Request, status
from fastapi.concurrency import asynccontextmanager
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from strawberry.fastapi import GraphQLRouter
from strawberry.subscriptions import GRAPHQL_TRANSPORT_WS_PROTOCOL, GRAPHQL_WS_PROTOCOL
from src.config import init_settings
from src.constants.http import ERROR_STATUS_CODES, INTERNAL_ERROR_DETAIL
from src.errors import InvalidRangeError
from src.schema.strawberry_schema import schema
from src.context import get_cache_service, get_context, init_task_infrastructure
from src.db.setup_mongo import setup_mongo
from src.logger import get_logger, setup_logger
from src.features.playback import video_router

logger = get_logger("app")


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Answer an error from src/errors.py with the status ERROR_STATUS_CODES gives it.

    :param request: The request whose handling raised the error.
    :type request: Request
    :param exc: The error that escaped the route.
    :type exc: Exception
    :return: The error message as the response detail.
    :rtype: JSONResponse
    """
    logger.warning(f"{type(exc).__name__} on path {request.url.path}: {exc}")
    headers = (
        {"Content-Range": f"bytes */{exc.file_size}"}
        if isinstance(exc, InvalidRangeError) else None
    )
    return JSONResponse(
        # isinstance rather than a lookup by type(exc): starlette also routes subclasses here.
        status_code=next(code for t, code in ERROR_STATUS_CODES.items() if isinstance(exc, t)),
        content={"detail": str(exc)},
        headers=headers,
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Answer any other error with a 500 whose detail does not reveal the error itself.

    :param request: The request whose handling raised the error.
    :type request: Request
    :param exc: The error that escaped the route.
    :type exc: Exception
    :return: A generic 500 response.
    :rtype: JSONResponse
    """
    logger.opt(exception=exc).error(f"Unhandled exception on path {request.url.path}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": INTERNAL_ERROR_DETAIL},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register the handlers that turn errors escaping REST routes into responses.

    :param app: The application to register the handlers on.
    :type app: FastAPI
    """
    for error_type in ERROR_STATUS_CODES:
        app.add_exception_handler(error_type, app_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)


def create_app():
    settings = init_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logger(
            log_dir=settings.logging.log_dir,
            rotation=settings.logging.rotation,
            retention=settings.logging.retention,
        )
        asyncio.get_running_loop().set_default_executor(
            ThreadPoolExecutor(max_workers=settings.io_thread_pool_size, thread_name_prefix="storage-io")
        )
        await setup_mongo(settings.mongo)
        # Tasks run in the worker processes (src/workers/worker_migration.py); this process only queues
        # them and relays their progress, so restarting it never interrupts one.
        task_infrastructure = await init_task_infrastructure()
        yield
        await task_infrastructure.shutdown()
        await get_cache_service(settings).close()
        logger.info("Application shutdown")

    app = FastAPI(lifespan=lifespan)

    register_exception_handlers(app)

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
