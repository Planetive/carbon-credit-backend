"""
Railway entry point for FastAPI backend
"""
import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the FastAPI app
from fastapi_app.main import app

# Railway will use: uvicorn main:app
# The app is exported from fastapi_app.main
