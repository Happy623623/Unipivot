"""시나리오 자동 실행(PRD 8장 성공 지표와 테스트 시나리오).

    uv run python -m app.eval.cli --scenarios S01,S13 --now 2026-10-12T09:00:00+09:00

시나리오 하나 = `agent_runs` 한 줄(trigger `eval`, scenario_code)이고, 확인한 것은 그 아래
`tool_calls`에 `check`로 남는다. 성공률·응답시간·비용은 그 기록에서 나온다. 명세 12장의
`POST /internal/eval/run`은 `run_scenarios`를 부르는 얇은 겉이 된다(엔드포인트는 다음 일).
"""

from app.eval.runner import run_scenarios
from app.eval.scenarios import SCENARIOS, pick

__all__ = ["SCENARIOS", "pick", "run_scenarios"]
