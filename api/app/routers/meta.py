from fastapi import APIRouter

from app.auth import CurrentUserDep
from app.repositories.meta import MetaRepoDep
from app.schemas.meta import DepartmentList

router = APIRouter(prefix="/meta", tags=["메타"])


@router.get("/departments", response_model=DepartmentList)
async def list_departments(user: CurrentUserDep, meta: MetaRepoDep) -> DepartmentList:
    """온보딩·설정의 학과 선택 목록. 사용 중인 학과만 정렬 순서대로 준다 (로그인 필요)."""
    return DepartmentList(items=await meta.list_departments())
