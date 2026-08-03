from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from .models import (
    HealthResponse,
    FinanceEmissionRequest,
    FinanceEmissionResponse,
    FacilitatedEmissionRequest,
    FacilitatedEmissionResponse,
    ScenarioRequest,
    ScenarioResponse,
)
from .calculation_engine import CalculationEngine
from .scenario_engine import ScenarioEngine
from .auth_routes import router as auth_router
from .database import test_connection, get_supabase_client
from .db import engine as pg_engine, test_postgres_connection
from .finance_models import CompanyType
from .routers.profiles import router as profiles_router
from .routers.organizations import router as organizations_router
from .routers.counterparties import router as counterparties_router
from .routers.exposures import router as exposures_router
from .routers.company_emissions import router as company_emissions_router
from .routers.emission_assessments import router as emission_assessments_router
from .routers.emission_activities import router as emission_activities_router
from .routers.financed_emissions import router as financed_emissions_router
from .routers.catalog import router as catalog_router
from .routers.factors import router as factors_router
from .routers.calc import router as calc_router
import logging
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


app = FastAPI(title="Finance Emission Service", version="0.1.0")

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(profiles_router, prefix="/api/v1")
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(counterparties_router, prefix="/api/v1")
app.include_router(exposures_router, prefix="/api/v1")
app.include_router(company_emissions_router, prefix="/api/v1")
app.include_router(emission_assessments_router, prefix="/api/v1")
app.include_router(emission_activities_router, prefix="/api/v1")
app.include_router(financed_emissions_router, prefix="/api/v1")
app.include_router(catalog_router, prefix="/api/v1")
app.include_router(factors_router, prefix="/api/v1")
app.include_router(calc_router, prefix="/api/v1")

# CORS configuration - allow frontend domain and local development
# When allow_credentials=True, you cannot use allow_origins=["*"]
# Must specify exact origins
# Can be overridden with ALLOWED_ORIGINS environment variable (comma-separated)
default_origins = [
    "https://www.rethinkcarbon.io",
    "https://rethinkcarbon.io",
    "http://localhost:5173",  # Vite dev server
    "http://localhost:3000",  # Alternative dev port
    "http://localhost:8080",  # Local dev server
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8080",
    "http://localhost:8000",  # Local backend (for testing)
    "http://127.0.0.1:8000",  # Local backend (for testing)
]

# Add Vercel preview URLs pattern support via regex (handled separately)
# Vercel preview URLs look like: https://project-name-xyz123.vercel.app

# Get allowed origins from environment variable or use defaults
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
if allowed_origins_env:
    allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",")]
else:
    allowed_origins = default_origins

logger.info(f"CORS allowed origins: {allowed_origins}")

# Add CORS middleware - MUST be added before routes
# For Vercel serverless functions, explicit CORS configuration is critical
# Note: When allow_credentials=True, allow_headers must be explicit, not ["*"]
# Using both allow_origins (explicit list) and allow_origin_regex (for localhost and Vercel preview URLs)
# This ensures production domains work while allowing any localhost port for development
# and Vercel preview deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Explicit list of allowed origins
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|https://.*\.vercel\.app",  # Allow localhost and Vercel preview URLs
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "Accept",
        "Origin",
        "X-Requested-With",
        "Access-Control-Request-Method",
        "Access-Control-Request-Headers",
    ],
    expose_headers=["*"],
    max_age=3600,
)

# Bank portfolio management removed - keeping simple individual company approach

# Initialize the calculation engines lazily to avoid crashes during import
calculation_engine = None
scenario_engine = None

def get_calculation_engine():
    """Lazy initialization of calculation engine"""
    global calculation_engine
    if calculation_engine is None:
        calculation_engine = CalculationEngine()
    return calculation_engine

def get_scenario_engine():
    """Lazy initialization of scenario engine"""
    global scenario_engine
    if scenario_engine is None:
        scenario_engine = ScenarioEngine()
    return scenario_engine


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    # Prefer self-hosted Postgres when DATABASE_URL is set; else legacy Supabase probe
    if test_postgres_connection():
        db_status = "connected"
    else:
        db_status = "connected" if test_connection() else "disconnected"
    return HealthResponse(
        status="ok", 
        engine_version="1.0.0",
        database_status=db_status
    )


@app.get("/")
def root():
    """Simple root endpoint for testing"""
    return {"message": "FastAPI backend is running!", "status": "ok"}


@app.get("/test-db")
def test_database():
    """
    Test database connection endpoint.
    Prefers EC2 Postgres (DATABASE_URL); falls back to legacy Supabase client.
    """
    if pg_engine is not None:
        try:
            with pg_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                profiles_count = None
                try:
                    profiles_count = conn.execute(
                        text("SELECT COUNT(*) FROM public.profiles")
                    ).scalar()
                except Exception:
                    # profiles table may not exist yet on a fresh DB
                    pass
            return {
                "status": "success",
                "backend": "postgres",
                "message": "Postgres connection successful",
                "tables_accessible": True,
                "profiles_count": profiles_count,
            }
        except Exception as e:
            logger.warning(f"Postgres test-db failed, trying Supabase fallback: {e}")

    # Legacy Supabase fallback
    try:
        client = get_supabase_client()
        result = client.table("profiles").select("id").limit(1).execute()

        return {
            "status": "success",
            "backend": "supabase",
            "message": "Database connection successful (legacy Supabase)",
            "tables_accessible": True,
            "sample_data_count": len(result.data) if result.data else 0,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Database connection failed: {str(e)}",
            "tables_accessible": False,
        }


@app.post("/finance-emission", response_model=FinanceEmissionResponse)
def finance_emission(req: FinanceEmissionRequest) -> FinanceEmissionResponse:
    """
    Calculate financed emissions using PCAF methodology
    """
    try:
        logger.info(f"Calculating finance emission for formula: {req.formula_id}")
        
        # Convert company_type string to enum
        company_type = CompanyType.LISTED if req.company_type == "listed" else CompanyType.PRIVATE
        
        # Perform calculation
        calc_result = get_calculation_engine().calculate(
            formula_id=req.formula_id,
            inputs=req.inputs,
            company_type=company_type
        )
        
        # Convert finance_models.CalculationResult to models.CalculationResult
        # The difference is calculation_steps: List[CalculationStep] vs List[Dict[str, Any]]
        from .models import CalculationResult as ModelsCalculationResult
        result = ModelsCalculationResult(
            attribution_factor=calc_result.attribution_factor,
            emission_factor=calc_result.emission_factor,
            financed_emissions=calc_result.financed_emissions,
            data_quality_score=calc_result.data_quality_score,
            methodology=calc_result.methodology,
            calculation_steps=[
                {
                    "step": step.step,
                    "value": step.value,
                    "formula": step.formula
                }
                for step in calc_result.calculation_steps
            ],
            metadata=calc_result.metadata
        )
        
        # Convert result to response format
        response = FinanceEmissionResponse(
            success=True,
            result=result,
            calculation_id=None  # TODO: Save to database and return ID
        )
        
        logger.info(f"Finance emission calculation completed successfully")
        return response
        
    except ValueError as e:
        logger.error(f"Validation error in finance emission calculation: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error in finance emission calculation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal calculation error")


@app.post("/facilitated-emission", response_model=FacilitatedEmissionResponse)
def facilitated_emission(req: FacilitatedEmissionRequest) -> FacilitatedEmissionResponse:
    """
    Calculate facilitated emissions using PCAF methodology
    """
    try:
        logger.info(f"Calculating facilitated emission for formula: {req.formula_id}")
        
        # Convert company_type string to enum
        company_type = CompanyType.LISTED if req.company_type == "listed" else CompanyType.PRIVATE
        
        # Perform calculation
        calc_result = get_calculation_engine().calculate(
            formula_id=req.formula_id,
            inputs=req.inputs,
            company_type=company_type
        )
        
        # Convert finance_models.CalculationResult to models.CalculationResult
        # The difference is calculation_steps: List[CalculationStep] vs List[Dict[str, Any]]
        from .models import CalculationResult as ModelsCalculationResult
        result = ModelsCalculationResult(
            attribution_factor=calc_result.attribution_factor,
            emission_factor=calc_result.emission_factor,
            financed_emissions=calc_result.financed_emissions,
            data_quality_score=calc_result.data_quality_score,
            methodology=calc_result.methodology,
            calculation_steps=[
                {
                    "step": step.step,
                    "value": step.value,
                    "formula": step.formula
                }
                for step in calc_result.calculation_steps
            ],
            metadata=calc_result.metadata
        )
        
        # Convert result to response format
        response = FacilitatedEmissionResponse(
            success=True,
            result=result,
            calculation_id=None  # TODO: Save to database and return ID
        )
        
        logger.info(f"Facilitated emission calculation completed successfully")
        return response
        
    except ValueError as e:
        logger.error(f"Validation error in facilitated emission calculation: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error in facilitated emission calculation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal calculation error")


@app.options("/scenario/calculate")
def options_scenario():
    """Handle OPTIONS preflight requests for scenario endpoint"""
    logger.info("OPTIONS preflight request received for /scenario/calculate")
    return {"message": "OK"}


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests for debugging CORS and request flow"""
    origin = request.headers.get("origin", "No origin header")
    logger.info(f"Request: {request.method} {request.url.path} - Origin: {origin}")
    response = await call_next(request)
    # Log CORS headers in response
    cors_origin = response.headers.get("access-control-allow-origin", "Not set")
    logger.info(f"Response: {request.method} {request.url.path} - Status: {response.status_code} - CORS Origin: {cors_origin}")
    return response


@app.post("/scenario/calculate", response_model=ScenarioResponse)
def calculate_scenario(req: ScenarioRequest) -> ScenarioResponse:
    """
    Calculate climate stress testing scenarios using sector-specific multipliers
    """
    try:
        logger.info(f"POST /scenario/calculate - Calculating {req.scenario_type} scenario for {len(req.portfolio_entries)} portfolio entries")
        
        # Validate portfolio entries
        if not req.portfolio_entries:
            logger.warning("POST /scenario/calculate - Empty portfolio entries received")
            raise ValueError("Portfolio entries cannot be empty")
        
        # Perform scenario calculation
        result = get_scenario_engine().calculate_scenario(
            portfolio_entries=req.portfolio_entries,
            scenario_type=req.scenario_type
        )
        
        if not result.success:
            logger.error(f"POST /scenario/calculate - Scenario calculation failed: {result.error}")
            raise ValueError(result.error or "Scenario calculation failed")
        
        logger.info(f"POST /scenario/calculate - Success! Total loss increase: {result.total_loss_increase_percentage:.2f}%")
        return result
        
    except ValueError as e:
        logger.error(f"POST /scenario/calculate - Validation error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"POST /scenario/calculate - Internal error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal scenario calculation error")


# Local dev entrypoint: uvicorn fastapi_app.main:app --reload --host 0.0.0.0 --port 8000
