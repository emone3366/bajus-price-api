"""
Cron endpoints for Vercel Scheduler.
"""

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

from src.config import settings
from src.tasks import run_scraper_job

router = APIRouter(prefix="/cron", tags=["Cron"])

# Define the API Key header scheme for securing cron jobs
cron_api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


async def verify_cron_secret(api_key: str = Security(cron_api_key_header)) -> str:
    """Verify the cron secret against the configured admin secret."""
    expected_secret = f"Bearer {settings.admin_secret}"
    
    # Also support simple Bearer token or just the raw secret
    if not api_key or (api_key != expected_secret and api_key != settings.admin_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing cron secret",
        )
    return api_key


@router.post("/scrape", status_code=status.HTTP_202_ACCEPTED)
async def trigger_scrape(api_key: str = Depends(verify_cron_secret)) -> dict:
    """
    Manually trigger the scraper job.
    Designed to be called by Vercel Cron.
    """
    # Trigger the scraper (you could also background this task using BackgroundTasks,
    # but Vercel has a generous timeout for hobby/pro crons so awaiting is fine if 
    # the scraping is fast enough. Playwright usually takes a few seconds).
    await run_scraper_job()
    return {"status": "Scraper job completed"}
