"""서비스 워커에 보낼 푸시 페이로드와 누르면 갈 주소 (F-33, API 명세 10장).

주소 규칙은 **web과 같아야 한다**(`web/src/lib/notificationRoute.ts` + `routes.ts`). 알림함에서
누르는 곳과 푸시에서 누르는 곳이 다르면 학생이 다른 화면으로 간다. 규칙을 명세 10장에 적어 두고
두 쪽이 그것을 본다.

링크가 없는 알림(대상 id가 하나도 없는 알림)은 홈으로 보낸다 — 푸시는 눌러야 쓸모가 있다.
"""

import json
from dataclasses import dataclass
from urllib.parse import quote

HOME = "/"
ACADEMICS = "/academics"
TABS: dict[str, str] = {
    "lms_assignment": "assignments",
    "lms_module_item": "materials",
    "lms_announcement": "announcements",
}


@dataclass(frozen=True)
class PushPayload:
    """서비스 워커가 그대로 읽는 JSON(명세 10장의 "푸시 페이로드")."""

    type: str
    title: str
    body: str | None
    url: str
    notification_id: str

    def to_json(self) -> bytes:
        return json.dumps(
            {
                "type": self.type,
                "title": self.title,
                "body": self.body,
                "url": self.url,
                "notification_id": self.notification_id,
            },
            ensure_ascii=False,
        ).encode()


def url_for(
    *,
    kind: str,
    link_type: str | None,
    link_id: str | None,
    course_id: str | None,
) -> str:
    """알림 하나가 가리키는 web 주소. `routeToHref`와 같은 꼴을 만든다."""
    if link_type is None or link_id is None:
        return HOME
    if link_type == "opportunity":
        focus = "?focus=profile_input" if kind == "profile_needed" else ""
        return f"/opportunities/{quote(link_id, safe='')}{focus}"
    if link_type == "planner_task":
        return "/planner"
    # lms_* 알림은 과목 탭으로 간다. 과목을 못 찾으면(수강을 뺐다) 학업 화면까지만
    if course_id is None:
        return ACADEMICS
    tab = TABS.get(link_type)
    suffix = f"?tab={tab}" if tab else ""
    return f"{ACADEMICS}/{quote(course_id, safe='')}{suffix}"


def payload_for(
    *,
    notification_id: str,
    kind: str,
    title: str,
    body: str | None,
    link_type: str | None,
    link_id: str | None,
    course_id: str | None,
) -> PushPayload:
    return PushPayload(
        type=kind,
        title=title,
        body=body,
        url=url_for(kind=kind, link_type=link_type, link_id=link_id, course_id=course_id),
        notification_id=notification_id,
    )
