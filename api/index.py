"""Vercel entry point for the Django WSGI application."""

from config.wsgi import application as app

__all__ = ["app"]
