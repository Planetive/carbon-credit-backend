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
# Wrap in a function to avoid Vercel's handler inspection issues
_mangum_handler = Mangum(app, lifespan="off", api_gateway_base_path="")

def handler(event, context):
    """Vercel serverless function handler"""
    return _mangum_handler(event, context)