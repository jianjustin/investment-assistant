from fastapi import APIRouter, HTTPException

from investment_assistant.tasks import runner

router = APIRouter()


@router.get("/api/runs/{run_id}")
def get_run(run_id: str):
    rec = runner.get(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="unknown run")
    return rec
