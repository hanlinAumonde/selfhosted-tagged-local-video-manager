import sys
from pathlib import Path
from loguru import logger

from src.constants.log import CONSOLE_FORMAT, FILE_FORMAT


def console_filter(record: dict) -> bool:
    """Console filter: Info and Warning levels"""
    return record["level"].name in ("INFO", "WARNING")


def error_filter(record: dict) -> bool:
    """Error file filter: Only allow ERROR and above"""
    return record["level"].no >= logger.level("ERROR").no


def setup_logger(
    log_dir: str | Path = "logs",
    console_format: str = CONSOLE_FORMAT,
    file_format: str = FILE_FORMAT,
    rotation: str = "10 MB",
    retention: str = "30 days",
) -> None:
    """
    Configure the logging system

    :param log_dir: Directory for log files
    :type log_dir: str | Path
    :param console_format: Console output format
    :type console_format: str
    :param file_format: File output format
    :type file_format: str
    :param rotation: Log rotation size
    :type rotation: str
    :param retention: Log retention time
    :type retention: str
    """
    logger.remove()

    # Ensure the log directory exists
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger.add(
        sys.stderr,
        format=console_format,
        level="DEBUG",  # Set minimum level, actual output controlled by filter
        filter=console_filter,
        colorize=True,
    )

    logger.add(
        log_path / "error.log",
        format=file_format,
        level="ERROR",
        filter=error_filter,
        rotation=rotation,
        retention=retention,
        backtrace=True,      # Show full traceback
        diagnose=False,       
        encoding="utf-8",
    )


def get_logger(name: str = None):
    """
    Get a logger bound with the module name

    :param name: Module name, e.g., "video_stream_resolver"
    :type name: str
    :return: Logger instance bound with the module name
    """
    if name:
        return logger.bind(name=name)
    return logger
