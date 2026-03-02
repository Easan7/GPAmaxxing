"""Analytics package for student-state computation from Supabase data."""

from app.models.analytics.student_state import StudentState, build_student_state

__all__ = ["StudentState", "build_student_state"]
