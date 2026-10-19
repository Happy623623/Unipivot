"""온통청년 클라이언트를 만드는 자리 (F-11). 시험은 이 의존을 가짜 클라이언트 공장으로 바꾼다."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends

from app.youth.client import YouthPolicyClient

ClientFactory = Callable[[str], YouthPolicyClient]


def youth_client_factory() -> ClientFactory:
    return YouthPolicyClient


YouthClientFactoryDep = Annotated[ClientFactory, Depends(youth_client_factory)]
