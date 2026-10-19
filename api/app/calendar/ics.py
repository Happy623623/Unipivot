""".ics 파일 만들기 (F-34, RFC 5545).

Google 캘린더를 쓰지 않는 학생이 마감일·수업 일정을 iPhone·삼성·Outlook 캘린더에 넣는 파일이다.
표준 라이브러리만으로 만든다 — VEVENT 몇 개에 필요한 건 줄 접기(75바이트)와 글자 피하기뿐이고,
시각은 모두 UTC(`Z`)로 적어 시간대 블록(VTIMEZONE) 없이도 어느 앱에서나 같은 시각이 된다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

PRODID = "-//UNIPIVOT//UNIPIVOT Calendar//KO"
UID_DOMAIN = "unipivot"
LINE_LIMIT = 75  # RFC 5545 3.1: 한 줄은 75바이트까지, 넘치면 다음 줄을 공백 하나로 시작한다


@dataclass(frozen=True)
class IcsEvent:
    """파일에 들어갈 일정 하나. `starts_at`·`ends_at`은 시간대가 있는 시각이어야 한다."""

    uid: str  # 대상 id로 만든다. 같은 파일을 두 번 넣어도 캘린더 앱이 하나로 합친다
    title: str
    starts_at: datetime
    ends_at: datetime


def event_uid(kind: str, target_id: str) -> str:
    """`opportunity-<uuid>@unipivot`처럼 대상 종류와 id로 만든 UID."""
    return f"{kind}-{target_id}@{UID_DOMAIN}"


def escape_text(value: str) -> str:
    """TEXT 값의 특수 글자(역슬래시·`;`·`,`·줄바꿈)를 RFC 5545 3.3.11대로 피한다."""
    return (
        value.replace("\\", r"\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\r\n", "\n")
        .replace("\n", r"\n")
    )


def fold_line(line: str) -> str:
    """75바이트가 넘는 줄을 접는다. 한글(3바이트) 한가운데서는 자르지 않는다."""
    data = line.encode("utf-8")
    parts: list[bytes] = []
    while len(data) > LINE_LIMIT:
        cut = LINE_LIMIT
        while cut > 1 and (data[cut] & 0xC0) == 0x80:  # UTF-8 이어지는 바이트면 앞으로 물린다
            cut -= 1
        parts.append(data[:cut])
        data = b" " + data[cut:]
    parts.append(data)
    return b"\r\n".join(parts).decode("utf-8")


def utc_stamp(value: datetime) -> str:
    """`20261024T090000Z` 꼴. 시간대 없는 시각은 받지 않는다."""
    if value.tzinfo is None:
        raise ValueError("시간대가 없는 시각이에요.")
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def render_calendar(events: Sequence[IcsEvent], *, now: datetime) -> str:
    """VCALENDAR 문서. 줄 끝은 CRLF이고 일정은 시작 시각·제목 순이다."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    stamp = utc_stamp(now)
    for event in sorted(events, key=lambda one: (one.starts_at, one.title)):
        lines += [
            "BEGIN:VEVENT",
            f"UID:{event.uid}",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{utc_stamp(event.starts_at)}",
            f"DTEND:{utc_stamp(event.ends_at)}",
            f"SUMMARY:{escape_text(event.title)}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_line(line) for line in lines) + "\r\n"
