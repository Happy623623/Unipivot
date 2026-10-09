# LLM 작업별 기본 모델 — 돈 안 들이고 시작하기

> 📝 기준: PRD v0.9 6·7·14장 · 가격과 조건은 각 사 공식 문서(2026-10-07·08 확인) · 2026-10-08
>
> 함께 보는 파일: `PRD_v0.9.md`(6장 요건 추출 에이전트, 14장 미결 사항) · `API_뼈대_구현.md`(`app/pricing.py`)

PRD 14장의 미결 사항인 "LLM 작업별 기본 모델"을 정한 문서다. 10/8에 "지원 자금이 없으니 최대한 돈을 쓰지 않는다. 모델은 나중에 바꿀 수 있다"로 방향을 정하고, Google Cloud 무료 체험 크레딧으로 Gemini를 쓰기로 했다. Claude는 자금이 생기면 비교에 더한다. 공급사와 모델은 래퍼 설정으로 바꿀 수 있게 만든다(PRD 6장).

## 정한 것 (10/8)

| # | 항목 | 정한 내용 |
| --- | --- | --- |
| 1 | 돈 안 드는 방법 | Google Cloud 무료 체험 크레딧($300, 90일)으로 Gemini 플랫폼(구 Vertex AI)에서 부른다. 청구는 0원이고 입력을 학습에 쓰지 않는다 |
| 2 | 작업별 모델 | 요건 추출·포스터·스캔 첨부·강의계획서는 Gemini 3.8 Flash, 서류 안내와 P1 작업은 Gemini 3.5 Flash-Lite |
| 3 | 확정 방법 | S1-4 끝(W3, 10/18까지)에 정답셋 공고 15건과 포스터 5장으로 3.8 Flash와 3.5 Flash-Lite를 비교한다. 청구 0원 |
| 4 | 사업계획서 비용 | 2027년 단가로 계산한다. Gemini 3.8 Flash는 2027-01-01부터 단가가 두 배다 |
| 5 | 체험이 끝나면 | 가입하고 90일 뒤(10/8 가입이면 1월 초)에 끝난다. 12월 말에 무료 등급, 유료 등급, 지원 자금 중 다음 방법을 정한다 |
| 6 | 역할 | 결제는 팀원 한 명이 맡고(체험 가입·예산 알림), 개발은 팀장 혼자 한다. 팀장은 프로젝트 소유자로 자기 계정을 쓴다 |

## 설정 순서

결제는 팀원 한 명이 맡고, 개발은 팀장 혼자 한다(10/8). 카드 정보와 계정 비밀번호는 주고받지 않는다. 결제 계정은 팀원 것이고, 팀장은 프로젝트 소유자로 자기 계정을 써서 개발한다.

**결제를 맡은 팀원** (10분)

1. 본인 Google 계정으로 [Google Cloud 무료 체험](https://cloud.google.com/free)을 시작한다. 카드를 등록하지만 체험 중에도 끝난 뒤에도 자동 청구는 없다. Google Cloud·Firebase·Maps를 유료로 쓴 적이 없고 체험도 처음인 계정이어야 한다
2. 프로젝트를 만들고(예: `unipivot`) 프로젝트 ID를 팀장에게 알려 준다
3. IAM에서 팀장의 Google 계정을 추가하고 역할 "소유자"를 준다. 초대 메일이 가면 팀장이 수락한다
4. 결제의 예산 및 알림에서 월 예산을 $30 정도로 만들고 50·90·100% 알림을 건다. 알림은 결제 계정 관리자인 팀원에게 간다. 팀장도 크레딧 잔액을 보게 하려면 결제 계정 관리에서 팀장을 "결제 계정 뷰어"로 추가한다
5. "업그레이드"(유료 계정 활성화)는 누르지 않는다. 누르면 남은 크레딧을 다 쓴 뒤부터 카드로 청구된다. 누르지 않으면 90일 뒤 프로젝트가 멈출 뿐 청구는 없다

**팀장**

6. API 라이브러리에서 Vertex AI API(`aiplatform.googleapis.com`)를 사용 설정한다. 콘솔에서는 이름이 Agent Platform으로 보일 수 있다
7. PC에 [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)를 설치하고 아래를 실행한다. 로그인할 때 설정한 프로젝트가 사용량 기준 프로젝트로 함께 기록된다

```powershell
gcloud config set project <프로젝트 ID>
gcloud auth application-default login
```

8. API 뼈대가 들어간 레포의 `api/scripts/`에 아래 파일을 두고, `api` 폴더에서 실행한다. "연결됨"과 토큰 수가 나오면 끝이다

```powershell
uv run --no-project --with google-genai python scripts/check_gemini.py <프로젝트 ID>
```

#### `api/scripts/check_gemini.py`

```python
"""Gemini 플랫폼(구 Vertex AI) 연결 확인. api 폴더에서 실행한다.

    uv run --no-project --with google-genai python scripts/check_gemini.py <프로젝트 ID>

먼저 gcloud auth application-default login 으로 로그인해 둔다. 크레딧에서 1원도 안 되는 금액이 빠진다.
"""

import sys

from google import genai
from google.genai import types

client = genai.Client(enterprise=True, project=sys.argv[1], location="global")
response = client.models.generate_content(
    model="gemini-3.8-flash",
    contents="연결 확인이야. '연결됨' 한 단어로만 답해.",
    config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
    ),
)
usage = response.usage_metadata
print(response.text)
print(
    f"입력 {usage.prompt_token_count} · 출력 {usage.candidates_token_count}"
    f" · 생각 {usage.thoughts_token_count or 0} 토큰"
)
```


## 작업별 모델 (잠정)

| 작업 | 기본 | 비교 상대 | 이유 |
| --- | --- | --- | --- |
| 요건 추출 에이전트 | Gemini 3.8 Flash (생각 low) | Gemini 3.5 Flash-Lite | 판정 정확도가 걸린 작업이라 가장 최근 Flash로 시작한다 |
| 첨부 이미지·스캔 읽기 | Gemini 3.8 Flash | Gemini 3.5 Flash-Lite | PDF를 그대로 받고 쪽당 560토큰이다 |
| 포스터 추출 | Gemini 3.8 Flash | Gemini 3.5 Flash-Lite | 작은 글씨가 많다. 이미지를 2,240토큰까지 올릴 수 있다 |
| 강의계획서 파싱 | Gemini 3.8 Flash | Gemini 3.5 Flash-Lite | 뽑은 날짜가 캘린더에 들어간다 |
| 서류 안내 | Gemini 3.5 Flash-Lite | Gemini 3.8 Flash | 사실은 서류 사전이 정하고 LLM은 잇기만 하는 짧은 생성이다 |
| (P1) 공지 분류 | Gemini 3.5 Flash-Lite | — | 짧은 분류다 |
| (P1) 강의자료 요약 | Gemini 3.5 Flash-Lite | Gemini 3.8 Flash | 입력이 길다 |

### 비교 실험 (확정 방법)

- **언제**: S1-4 요건 추출 에이전트가 돌고, 정답셋(S1-7)이 다 모이면 한다. W3 끝(10/18)이 목표다
- **무엇을**: 공고 15건(학교 장학 10, 청년정책 5)과 포스터 5장을 3.8 Flash(생각 low)와 3.5 Flash-Lite로 돌린다. 프롬프트, 도구, 스키마, 첨부 텍스트 추출 결과는 같고 모델만 바꾼다
- **볼 것**: 요건 항목 일치율, 마감일 일치율, 판정 혼동행렬(가상 프로필 5종)의 "실제 적격 → 부적격" 건수, 스키마 재시도율, 공고당 비용, p50·p95 응답시간. 모두 `agent_runs`·`llm_calls`에서 나온다
- **고르는 순서(제안)**: ① "실제 적격 → 부적격"이 적은 모델 ② 같으면 요건 항목 일치율이 높은 모델 ③ 일치율 차이가 5%p 안이면 비용과 p95가 나은 모델
- **비용**: 체험 크레딧에서 빠지므로 청구 0원이다. 목록 단가로 치면 $0.56 정도다

3.5 Flash-Lite가 정확도에서 밀리지 않으면 작업 비용이 1/2–1/4로 준다. 결과는 W6 베이스라인과 W9–10 개선 전후 비교표의 첫 줄이 된다.

## 자금이 생기면

- Claude Haiku 4.5를 요건 추출의 비교 상대로 더한다. 10/7에 정리한 혼합안(요건 추출·서류 안내·강의계획서는 Haiku 4.5, 이미지는 Gemini 3.8 Flash)이 그때의 후보다. 생각 토큰이 없어 응답시간과 비용이 일정하고, strict 도구로 도구 입력이 스키마를 따르고, 2027년에도 단가가 그대로다
- Claude 두 모델의 단가도 단가표에 이미 넣어 두었다. 래퍼에 공급사만 더하면 비교할 수 있다

## 참고: 돈 안 드는 방법 비교

10/8에 ②를 골랐다. 체험이 끝난 뒤나 문제가 생겼을 때 다시 볼 수 있게 남긴다.

| | ① Gemini API 무료 등급 | **② Cloud 무료 체험 + Gemini 플랫폼 (고름)** | ③ Gemini API 유료 등급 |
| --- | --- | --- | --- |
| 드는 돈 | 0원 | 0원. $300 크레딧을 90일 동안 쓴다 | $5 선불부터. 크레딧은 12개월 뒤 만료 |
| 필요한 것 | Google 계정, AI Studio 키 | 결제 카드 등록. 체험 중에도 끝난 뒤에도 자동 청구는 없다. Google Cloud·Firebase·Maps를 유료로 쓴 적이 없고 체험도 처음인 계정이어야 한다 | 결제 카드 |
| 입력을 학습에 쓰나 | **쓴다.** 사람이 볼 수 있고, 개인정보·민감 정보를 넣지 말라고 돼 있다 | 쓰지 않는다. 남용 감지용으로만 프롬프트를 기록할 수 있다 | 쓰지 않는다 |
| 한도 | 낮다. 숫자는 문서에 없고 AI Studio 한도 화면에서만 보인다 | 무료 등급보다 넉넉하다. 체험 중에는 할당량 증가를 요청할 수 없다 | 무료 등급보다 넉넉하다. 월 지출 한도를 걸 수 있다 |
| 끝 | — | 90일 뒤 업그레이드하지 않으면 체험 결제 계정이 닫힌다. 10/8에 가입하면 1월 초라 최종 데모(W11)까지는 충분하다 | 잔액이 0이 되면 키가 멈춘다 |
| PRD 7장 "외부 LLM" | **충돌한다.** "입력 학습 미사용 조건을 확인한다"와 맞지 않는다 | 그대로 둔다 | 그대로 둔다 |

알아 둘 것은 이렇다.
- **①로 옮길 때**: 공개된 학교 공고와 청년정책만 보낸다. 포스터와 강의계획서는 팀원이 만든 테스트 자료로만 돌리고, PRD 7장 문구도 바꾼다
- **체험 크레딧이 빠지는 곳**: Gemini 플랫폼(구 Vertex AI)으로 불러야 한다. 2026-03-02 이후에 만든 계정은 Gemini API(AI Studio) 사용분에 크레딧을 쓸 수 없다
- **단가**: Gemini 플랫폼의 global 단가는 Gemini API와 같다. 서울 같은 리전을 지정하면 10% 비싸다
- **Claude**: 돈을 내지 않고 쓰는 방법을 공식 문서에서 찾지 못했다. 체험 크레딧도 Gemini 플랫폼에 올라온 파트너 모델(Claude 등)에는 쓸 수 없다

## 참고: 작업, 후보 모델, 비용

### 작업과 필요한 능력

| 작업 | 언제 도나 | 필요한 능력 |
| --- | --- | --- |
| 요건 추출 에이전트 | 정기 배치. 공고 1건에 1회, 모든 사용자가 공유 | 도구 호출, 구조화 출력, 긴 한국어 문서 |
| 첨부 이미지·스캔 읽기 (`read_attachment_image`) | 요건 추출 안의 도구 | Vision, PDF |
| 포스터 추출 (F-13) | 사용자가 올릴 때. 결과를 기다린다 | Vision, 작은 글씨 |
| 서류 안내 | 준비하기 | 짧은 생성 |
| 강의계획서 파싱 | 업로드 | 날짜 구조화 추출 |
| (P1) 공지 분류 · 강의자료 요약 | LMS 새 공지 · 업로드 | 짧은 분류 · 긴 입력 |

### 후보 모델

| 모델 | API ID | 입력 / 출력 (USD, 100만 토큰) | 문맥 | 이미지 1장 · PDF 1쪽 토큰 | 메모 |
| --- | --- | --- | --- | --- | --- |
| Gemini 3.8 Flash | `gemini-3.8-flash` | 0.75 / 3.75 (2026-12-31까지) → 1.50 / 7.50 (2027-01-01부터) | 1M | 이미지 1,120(기본, 최대 2,240) · PDF 560(기본) | 2026-09-02 안정판. 생각을 끌 수 없다(low·medium·high, 기본 medium). 생각 토큰도 출력 단가로 낸다 |
| Gemini 3.5 Flash-Lite | `gemini-3.5-flash-lite` | 0.30 / 2.50 | 1M | 이미지 1,120 · PDF 560 | 안정판. 생각 기본 minimal |
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | 1 / 5 | 200K | 이미지 최대 1,568(긴 변 1,568px로 줄임) | 자금이 생기면 비교. 생각은 켤 때만, strict 도구 |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | 2 / 10 | 1M | 이미지 최대 4,784(긴 변 2,576px) | 정확도 상한 참고용 |

뺀 모델은 Gemini 2.5 Flash·Flash-Lite(예전에 쓰던 사용자만 접근 가능), Gemini 3.1 Flash-Lite(2027-05-07 종료 예정), Claude Haiku 3.5(구세대), Claude Opus·Fable(저가 범위 밖)이다.

### 비용 (목록 단가)

청구는 0원이어도 비용은 목록 단가로 계산해 `llm_calls`에 남긴다. PRD 8장 지표와 사업계획서에 쓰고, 나중에 유료로 바꿔도 같은 기준으로 비교하기 위해서다.

호출 1건의 토큰은 아래처럼 가정했다. S1-4에서 `llm_calls`에 실제 값이 쌓이면 바꾼다.
- **요건 추출**: 지시문·스키마·도구 정의 3,000, 본문 1,500, 첨부 텍스트 6,000. 본문을 보고 첨부를 읽은 뒤 제출하는 2턴이다(입력 15,150, 출력 1,500). Claude는 도구 사용 시스템 프롬프트(Haiku 4.5는 턴마다 496)를 더했다
- **스캔 첨부 1쪽**: 쪽 이미지 + 지시문 300, 옮겨 적은 글자 1,200
- **포스터 1장**: 사진 + 지시문 2,000, 출력 1,000
- **서류 안내**: 2,000 / 800. **강의계획서**: 7,000 / 1,000. **공지 분류**: 2,000 / 50. **강의자료 요약**: 30,000 / 1,500

작업 1건 비용이다(USD, 생각 토큰 제외).

| 작업 | Gemini 3.8 Flash (~2026-12-31) | Gemini 3.8 Flash (2027-01-01~) | Gemini 3.5 Flash-Lite | Claude Haiku 4.5 | Claude Sonnet 5.5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 요건 추출 (공고 1건) | $0.0170 | $0.0340 | $0.0083 | $0.0236 | $0.0464 |
| 스캔 첨부 1쪽 | $0.0051 | $0.0103 | $0.0033 | $0.0079 | $0.0222 |
| 포스터 1장 | $0.0061 | $0.0122 | $0.0034 | $0.0086 | $0.0236 |
| 서류 안내 1회 | $0.0045 | $0.0090 | $0.0026 | $0.0060 | $0.0120 |
| 강의계획서 1건 | $0.0090 | $0.0180 | $0.0046 | $0.0120 | $0.0240 |
| (P1) 공지 분류 1건 | $0.0017 | $0.0034 | $0.0007 | $0.0023 | $0.0045 |
| (P1) 강의자료 요약 1건 | $0.0281 | $0.0563 | $0.0128 | $0.0375 | $0.0750 |

Gemini 3.8 Flash는 생각을 끌 수 없어서, 생각 토큰 1,000개마다 $0.0038(2027년부터 $0.0075)가 더 붙는다.

시범 운영 한 달 비용이다. 사용자 100명, 공고 300건(학교 공지 200 + 청년정책 100), 스캔 첨부 40쪽, 포스터 200장, 준비하기 300회, 강의계획서 500건(학기 초)을 가정했다. Gemini 3.8 Flash는 호출마다 생각 토큰 1,000개로 잡았고, P0 작업만 넣었다.

| 구성 | 생각 토큰 제외 | Gemini 생각 토큰 | 합계 |
| --- | ---: | ---: | ---: |
| Gemini만 (지금) | $11.80 | $5.03 | $16.83 |
| 혼합 (자금이 생기면 후보) | $16.32 | $0.90 | $17.22 |
| Claude만 | $19.92 | $0.00 | $19.92 |

②의 크레딧 $300이면 지금 구성으로 시범 운영 석 달($16.83 × 3)을 쓰고도 남는다. 청년정책을 처음 한 번 500건 모으는 데는 Gemini 3.8 Flash로 $12.24다. ①의 무료 등급이면 하루 한도 때문에 며칠에 나눠야 할 수 있다.

입력을 학습에 쓰는지에 대한 근거다(PRD 7장 "외부 LLM").

| 공급사·등급 | 입력을 학습·제품 개선에 쓰나 | 근거 |
| --- | --- | --- |
| Gemini 플랫폼 (구 Vertex AI, ②) | 쓰지 않는다. 남용 감지용으로 프롬프트를 기록할 수 있다 | [Data governance and generative AI](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/data-governance) |
| Gemini API 유료 등급 (③) | 쓰지 않는다. 금지 행위를 감지하는 데만 기록한다 | [Gemini API 추가 약관](https://ai.google.dev/gemini-api/terms) |
| Gemini API 무료 등급 (①) | 쓴다. 사람이 볼 수 있고, 개인정보·민감 정보를 넣지 말라고 돼 있다 | 같은 약관 |
| Anthropic API (자금이 생기면) | 기본으로 쓰지 않는다. 피드백을 직접 보낸 경우 등은 예외 | [Is my data used for model training?](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training) |

## 단가표 넣기

API 뼈대(킥오프 Day 2)를 넣은 뒤 `api/app/pricing.py`를 아래로 바꾸고 `api/tests/test_pricing.py`를 더한다. 지금 쓰는 Gemini 두 모델과, 나중에 비교할 Claude 두 모델의 목록 단가를 넣었다. 적용 시작일은 가격을 확인한 날(2026-10-07)이고, Gemini 3.8 Flash는 2027-01-01 단가를 한 줄 더 넣었다.

- [ ] `uv run pytest` → `25 passed, 3 skipped`(판정 엔진까지 넣었으면 `110 passed, 3 skipped`). `scripts/check_gemini.py`는 테스트에 들어가지 않는다

#### `api/app/pricing.py`

```python
"""모델 단가표 (PRD 7장 비용). 비용을 이 표로 계산해서, 단가가 바뀌어도 개선 전후를 같은 기준으로 비교한다.

값은 100만 토큰당 USD이고, 같은 모델은 적용 시작일 순서로 둔다. 단가가 바뀌면 기존 줄을 고치지 말고
새 적용일로 한 줄을 더한다(지난 호출의 비용이 그대로 남는다). 표에 없는 모델을 부르면 KeyError가 난다.
출력 단가는 생각(thinking) 토큰에도 붙으므로, record_llm의 output_tokens에는 생각 토큰을 포함해 넘긴다
(Gemini는 candidates_token_count + thoughts_token_count, Claude는 usage.output_tokens).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Price:
    effective_from: date
    input_per_mtok: Decimal
    output_per_mtok: Decimal


# 2026-10-07에 공식 가격표에서 확인한 단가 (Gemini는 결제를 연결한 유료 등급 Standard)
# https://platform.claude.com/docs/en/about-claude/pricing
# https://ai.google.dev/gemini-api/docs/pricing
_CHECKED = date(2026, 10, 7)

# (provider, model) → 적용 시작일 순서의 단가. model은 API에 보내는 ID와 똑같이 쓴다
PRICES: dict[tuple[str, str], tuple[Price, ...]] = {
    ("anthropic", "claude-haiku-4-5-20251001"): (
        Price(_CHECKED, Decimal("1.00"), Decimal("5.00")),
    ),
    ("anthropic", "claude-sonnet-5-5"): (Price(_CHECKED, Decimal("2.00"), Decimal("10.00")),),
    ("google", "gemini-3.8-flash"): (
        Price(_CHECKED, Decimal("0.75"), Decimal("3.75")),  # 2026-12-31까지
        Price(date(2027, 1, 1), Decimal("1.50"), Decimal("7.50")),
    ),
    ("google", "gemini-3.5-flash-lite"): (Price(_CHECKED, Decimal("0.30"), Decimal("2.50")),),
}


def price_on(
    provider: str,
    model: str,
    on: date,
    prices: Mapping[tuple[str, str], tuple[Price, ...]] = PRICES,
) -> Price:
    history = prices.get((provider, model))
    if not history:
        raise KeyError(
            f"단가표에 없는 모델: {provider}/{model}. app/pricing.py의 PRICES에 넣어 주세요."
        )
    applicable = [price for price in history if price.effective_from <= on]
    if not applicable:
        raise KeyError(f"{provider}/{model}의 {on} 기준 단가가 없어요.")
    return max(applicable, key=lambda price: price.effective_from)


def cost_usd(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    on: date,
    prices: Mapping[tuple[str, str], tuple[Price, ...]] = PRICES,
) -> Decimal:
    """on 날짜에 적용되는 단가로 계산한 비용 (소수점 6자리, llm_calls.cost_usd와 같은 자릿수)."""
    price = price_on(provider, model, on, prices)
    total = price.input_per_mtok * input_tokens + price.output_per_mtok * output_tokens
    return (total / Decimal(1_000_000)).quantize(Decimal("0.000001"))
```

#### `api/tests/test_pricing.py`

```python
"""단가표 (PRD 7장 비용). 래퍼가 쓰는 모델 ID와 단가표 키가 같아야 비용이 계산된다."""

from datetime import date
from decimal import Decimal

from app.pricing import PRICES, cost_usd


def test_price_table_lists_candidate_models_in_date_order() -> None:
    assert set(PRICES) == {
        ("anthropic", "claude-haiku-4-5-20251001"),
        ("anthropic", "claude-sonnet-5-5"),
        ("google", "gemini-3.8-flash"),
        ("google", "gemini-3.5-flash-lite"),
    }
    for history in PRICES.values():
        dates = [price.effective_from for price in history]
        assert dates == sorted(dates)


def test_costs_from_price_table() -> None:
    # 입력 15,150 · 출력 1,500 토큰
    on = date(2026, 10, 7)
    assert cost_usd("anthropic", "claude-haiku-4-5-20251001", 15_150, 1_500, on) == Decimal(
        "0.022650"
    )
    assert cost_usd("google", "gemini-3.5-flash-lite", 15_150, 1_500, on) == Decimal("0.008295")


def test_gemini_flash_price_doubles_in_2027() -> None:
    million = 1_000_000
    before = cost_usd("google", "gemini-3.8-flash", million, million, date(2026, 12, 31))
    after = cost_usd("google", "gemini-3.8-flash", million, million, date(2027, 1, 1))
    assert (before, after) == (Decimal("4.500000"), Decimal("9.000000"))
```

## 래퍼를 만들 때 지킬 것 (S1-4)

- Gemini는 `google-genai` SDK로 부른다. `genai.Client(enterprise=True, project=..., location="global")`이다. 예전 이름인 `vertexai=True`도 아직 된다. 같은 SDK에서 `genai.Client(api_key=...)`로 바꾸면 Gemini API(무료·유료 등급)로 간다
- SDK는 `api/.env`를 직접 읽지 않는다. `Settings`에 `google_cloud_project`와 `google_cloud_location`(기본 `global`)을 더해 Client에 넘긴다
- `location`은 `global`로 둔다. 리전을 지정하면 단가표보다 10% 비싸다
- `record_llm`에 넘기는 토큰은 이렇게 센다. 입력은 `prompt_token_count + tool_use_prompt_token_count`, 출력은 `candidates_token_count + thoughts_token_count`다. 생각 토큰도 출력 단가로 낸다
- 모델 ID는 단가표 키와 똑같이 쓴다. 별칭을 쓰면 단가표에서 못 찾는다
- Gemini 3.8 Flash는 `thinking_level`을 low로 시작한다. 기본값(medium)이면 생각 토큰이 늘어난다
- 서버에 올릴 때의 인증(서비스 계정)은 배포할 곳을 정할 때 정한다. 키 파일을 쓰게 되면 레포에 넣지 않는다
- 개선 후보(W9–10): 프롬프트 캐싱, Batch 50% 할인. Batch는 도구를 고르는 루프라 그대로는 못 쓴다

## PRD와 레포에 반영하기

```text
docs/LLM_모델_선정.md를 docs/에 넣었어. 자금 없이 Gemini만 쓰고, Google Cloud 무료 체험 크레딧으로 Gemini 플랫폼에서 부르기로 했어.
1. docs/PRD_v0.9.md를 고쳐줘.
   - 14장 "LLM 작업별 기본 모델"은 체크하지 말고 "잠정: Gemini 3.8 Flash·3.5 Flash-Lite, Cloud 무료 체험 크레딧으로 0원 운영(docs/LLM_모델_선정.md). S1-4 끝에 정답셋으로 비교해 확정"으로 바꿔.
   - 6장 LLM 선택의 "W1에 같은 공고 20건으로 비교"를 "S1-4 끝(W3)에 정답셋 공고 15건·포스터 5장으로 Gemini 3.8 Flash와 3.5 Flash-Lite를 비교. Claude는 자금이 생기면 더한다"로 바꿔.
   - 7장 "외부 LLM" 행에 근거 링크를 붙여: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/data-governance
2. api/가 있으면 docs/LLM_모델_선정.md대로 api/app/pricing.py를 바꾸고 api/tests/test_pricing.py와 api/scripts/check_gemini.py를 추가해. 그다음 api에서 uv run ruff check ., uv run ruff format --check ., uv run pytest를 돌려.
끝나면 바뀐 곳을 알려줘.
```

## 출처

- Gemini: [가격](https://ai.google.dev/gemini-api/docs/pricing) · [결제](https://ai.google.dev/gemini-api/docs/billing) · [모델](https://ai.google.dev/gemini-api/docs/models) · [종료 일정](https://ai.google.dev/gemini-api/docs/deprecations) · [미디어 해상도](https://ai.google.dev/gemini-api/docs/media-resolution) · [생각](https://ai.google.dev/gemini-api/docs/thinking) · [추가 약관](https://ai.google.dev/gemini-api/terms) · [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- Google Cloud: [무료 체험](https://docs.cloud.google.com/free/docs/free-cloud-features) · [Gemini 플랫폼 (체험 크레딧 FAQ)](https://cloud.google.com/vertex-ai) · [Agent Platform 가격](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing) · [데이터 거버넌스](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/data-governance)
- Claude: [가격](https://platform.claude.com/docs/en/about-claude/pricing) · [모델 개요](https://platform.claude.com/docs/en/models/overview) · [Vision](https://platform.claude.com/docs/en/build-with-claude/vision) · [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) · [데이터 학습 정책](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training)
