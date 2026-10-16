"""LearningX(Canvas) 연동 (F-50·F-51·F-52). 클라이언트는 GET과 허용 경로만 쓴다."""

from app.lms.client import ALLOWED_PATHS, LearningXClient, LearningXError
from app.lms.parse import PORTAL_SYLLABUS_URL, CourseName, course_name

__all__ = [
    "ALLOWED_PATHS",
    "PORTAL_SYLLABUS_URL",
    "CourseName",
    "LearningXClient",
    "LearningXError",
    "course_name",
]
