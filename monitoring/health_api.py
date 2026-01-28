from fastapi import FastAPI, HTTPException
from datetime import datetime
from typing import Dict, Any
import os
from loguru import logger

app = FastAPI(title="Crypto Trading Bot Health API")

db_pool = None


async def get_database():
    global db_pool
    if db_pool is None:
        from learning.database_postgres import PostgresDatabase
        db = PostgresDatabase()
        await db.initialize()
        db_pool = db._pool
    return db_pool


@app.on_event("startup")
async def startup_event():
    try:
        await get_database()
        logger.info("Health API started successfully")
    except Exception as e:
        logger.error(f"Failed to start health API: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("Health API shutdown complete")


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    return {
        "status": "healthy",
        "service": "crypto-trading-bot",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/health/db")
async def database_health() -> Dict[str, Any]:
    try:
        pool = await get_database()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        
        return {
            "status": "healthy",
            "database": "connected",
            "pool_size": pool.get_size(),
            "pool_free": pool.get_idle_size(),
            "pool_max": pool.get_max_size(),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(status_code=503, detail={
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e)
        })


@app.get("/health/ready")
async def readiness_check() -> Dict[str, Any]:
    checks = {}
    all_healthy = True
    
    try:
        db_health = await database_health()
        checks["database"] = "healthy"
    except Exception as e:
        checks["database"] = f"unhealthy: {str(e)}"
        all_healthy = False
    
    env_vars = ["DATABASE_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    for var in env_vars:
        if os.getenv(var):
            checks[f"env_{var.lower()}"] = "set"
        else:
            checks[f"env_{var.lower()}"] = "missing"
            all_healthy = False
    
    status_code = 200 if all_healthy else 503
    
    if not all_healthy:
        raise HTTPException(status_code=status_code, detail={
            "ready": all_healthy,
            "checks": checks,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    return {
        "ready": all_healthy,
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/")
async def root():
    return {
        "service": "Crypto Trading Bot Health API",
        "endpoints": {
            "/health": "Basic health check",
            "/health/db": "Database connectivity",
            "/health/ready": "Readiness probe"
        }
    }
