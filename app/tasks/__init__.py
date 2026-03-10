"""
Tasks module.

This module contains all asynchronous tasks for the application.
Import all task modules here to ensure they are discovered.
"""

from .suggestions import create_suggestions
from .logging import log_audio_task

__all__ = [
    'create_suggestions', 
    'log_audio_task',
]
