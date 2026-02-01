"""
Structured logging configuration for AI Lightning.

Provides JSON logging for production and colored console logging for development.
"""
import logging
import sys
import json
from datetime import datetime
from typing import Any, Dict


class JSONFormatter(logging.Formatter):
    """
    Formatter that outputs JSON strings.
    Used for production logging that can be ingested by log aggregators.
    """
    
    def __init__(self, **kwargs):
        super().__init__()
        self.default_keys = kwargs
    
    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add default keys
        log_data.update(self.default_keys)
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        # Add extra fields
        if hasattr(record, 'extra'):
            log_data.update(record.extra)
        
        return json.dumps(log_data)


class ColoredFormatter(logging.Formatter):
    """
    Formatter that adds colors for console output.
    """
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging(
    app_name: str = 'ai-lightning',
    level: str = 'INFO',
    json_output: bool = False,
    log_file: str = None
):
    """
    Configure logging for the application.
    
    Args:
        app_name: Name of the application (used in JSON logs)
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: If True, output JSON formatted logs
        log_file: If provided, also log to this file
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # Clear existing handlers
    root_logger.handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    
    if json_output:
        formatter = JSONFormatter(app=app_name)
    else:
        formatter = ColoredFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (always JSON for easier parsing)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(JSONFormatter(app=app_name))
        root_logger.addHandler(file_handler)
    
    return root_logger


class LoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that adds extra context to all log messages.
    """
    
    def process(self, msg, kwargs):
        # Merge extra dict
        extra = kwargs.get('extra', {})
        extra.update(self.extra)
        kwargs['extra'] = extra
        return msg, kwargs


def get_logger(name: str, **extra) -> logging.Logger:
    """
    Get a logger with optional extra context.
    
    Args:
        name: Logger name
        **extra: Extra fields to add to all log messages
    
    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)
    if extra:
        return LoggerAdapter(logger, extra)
    return logger


# Request logging middleware for Flask
class RequestLogger:
    """
    Middleware for logging HTTP requests.
    """
    
    def __init__(self, app, logger=None):
        self.app = app
        self.logger = logger or logging.getLogger('requests')
    
    def __call__(self, environ, start_response):
        import time
        
        start_time = time.time()
        
        def custom_start_response(status, headers, exc_info=None):
            # Log the request
            duration = (time.time() - start_time) * 1000
            self.logger.info(
                f"{environ.get('REQUEST_METHOD')} {environ.get('PATH_INFO')} "
                f"- {status.split()[0]} - {duration:.2f}ms",
                extra={
                    'method': environ.get('REQUEST_METHOD'),
                    'path': environ.get('PATH_INFO'),
                    'status': status.split()[0],
                    'duration_ms': round(duration, 2),
                    'remote_addr': environ.get('REMOTE_ADDR'),
                    'user_agent': environ.get('HTTP_USER_AGENT', '')[:100]
                }
            )
            return start_response(status, headers, exc_info)
        
        return self.app(environ, custom_start_response)
