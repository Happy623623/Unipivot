from fastapi import APIRouter

router = APIRouter(tags=["상태"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
