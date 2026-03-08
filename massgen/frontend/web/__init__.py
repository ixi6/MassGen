"""
MassGen Web UI Module

Provides FastAPI-based web server for real-time coordination visualization.
"""

from .server import create_app, run_server

__all__ = ["create_app", "run_server"]
