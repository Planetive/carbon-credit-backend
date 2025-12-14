"""
Vercel serverless function entry point for FastAPI backend
"""
import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangum import Mangum
from fastapi_app.main import app

# Create ASGI handler for Vercel
# Use direct assignment - Vercel expects 'handler' to be a callable
handler = Mangum(app, lifespan="off")