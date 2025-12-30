"""
Logger singleton for centralized logging configuration.
"""
import os
import sys
import logging


class LoggerSingleton:
    """
    Singleton logger class to ensure consistent logging configuration across the application.
    """
    _instance = None
    _logger = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LoggerSingleton, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._setup_logger()
            LoggerSingleton._initialized = True

    def _setup_logger(self):
        """Configure the logger with appropriate handlers and format."""
        # Create logger
        self._logger = logging.getLogger('bgv_audit')
        
        # Set log level from environment or default to INFO
        log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
        self._logger.setLevel(getattr(logging, log_level, logging.INFO))
        
        # Prevent duplicate handlers
        if self._logger.handlers:
            return
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Console handler (stdout)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)
        
        # Error handler (stderr)
        error_handler = logging.StreamHandler(sys.stderr)
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        self._logger.addHandler(error_handler)

    @property
    def logger(self):
        """Get the logger instance."""
        if self._logger is None:
            self._setup_logger()
        return self._logger

    def debug(self, message: str):
        """Log debug message."""
        self.logger.debug(message)

    def info(self, message: str):
        """Log info message."""
        self.logger.info(message)

    def warning(self, message: str):
        """Log warning message."""
        self.logger.warning(message)

    def error(self, message: str):
        """Log error message."""
        self.logger.error(message)

    def critical(self, message: str):
        """Log critical message."""
        self.logger.critical(message)

    def exception(self, message: str):
        """Log exception with traceback."""
        self.logger.exception(message)


# Global logger instance
def get_logger() -> logging.Logger:
    """
    Get the singleton logger instance.
    
    Returns:
        logging.Logger: The configured logger instance
    """
    singleton = LoggerSingleton()
    return singleton.logger


# Convenience functions for direct logging
def log_debug(message: str):
    """Log debug message."""
    LoggerSingleton().debug(message)


def log_info(message: str):
    """Log info message."""
    LoggerSingleton().info(message)


def log_warning(message: str):
    """Log warning message."""
    LoggerSingleton().warning(message)


def log_error(message: str):
    """Log error message."""
    LoggerSingleton().error(message)


def log_critical(message: str):
    """Log critical message."""
    LoggerSingleton().critical(message)


def log_exception(message: str):
    """Log exception with traceback."""
    LoggerSingleton().exception(message)

