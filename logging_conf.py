import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

def setup_logging(env: str = "dev") -> logging.Logger:
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger
    
    common_fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S" 
    )
    error_fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console = logging.StreamHandler()
    console.setLevel(logging.INFO if env == "dev" else logging.WARNING)
    console.setFormatter(common_fmt)
    logger.addHandler(console)

    file_all = TimedRotatingFileHandler(
        LOG_DIR / "bot.log",
        when="D", interval=1, backupCount=7, encoding="utf-8"
    )
    file_all.setLevel(logging.DEBUG)
    file_all.setFormatter(common_fmt)
    logger.addHandler(file_all)

    file_err = TimedRotatingFileHandler(
        LOG_DIR / "errors.log",
        when="D", interval=1, backupCount=30, encoding="utf-8"
    )
    file_err.setLevel(logging.ERROR)
    file_err.setFormatter(error_fmt)
    logger.addHandler(file_err)

    logging.getLogger("aiogram").setLevel(logging.INFO if env == "dev" else logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    return logger