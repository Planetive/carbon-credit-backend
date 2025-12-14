"""
Vercel serverless function entry point for FastAPI backend
"""
import sys
import os

# Add the root directory to Python path so we can import fastapi_app
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root_dir)

from mangum import Mangum
from fastapi_app.main import app

# Create ASGI handler for Vercel
# Export handler - Vercel expects 'handler' to be a callable
handler = Mangum(app)