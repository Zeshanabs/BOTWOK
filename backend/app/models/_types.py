from sqlalchemy import Enum as SAEnum

from app.models import enums as E


def pg_enum(py_enum, name: str):
    return SAEnum(py_enum, name=name, native_enum=True, create_type=False, values_callable=lambda e: [m.value for m in e])


PlatformT = pg_enum(E.Platform, "platform_t")
MemberRoleT = pg_enum(E.MemberRole, "member_role_t")
ContentStatusT = pg_enum(E.ContentStatus, "content_status_t")
ScheduleStatusT = pg_enum(E.ScheduleStatus, "schedule_status_t")
RunStatusT = pg_enum(E.RunStatus, "run_status_t")
TaskStatusT = pg_enum(E.TaskStatus, "task_status_t")
ApprovalStatusT = pg_enum(E.ApprovalStatus, "approval_status_t")
AccountStatusT = pg_enum(E.AccountStatus, "account_status_t")
ContentFormatT = pg_enum(E.ContentFormat, "content_format_t")
ContentTypeT = pg_enum(E.ContentType, "content_type_t")
AvailabilityT = pg_enum(E.Availability, "availability_t")
RiskLevelT = pg_enum(E.RiskLevel, "risk_level_t")
AutomationStatusT = pg_enum(E.AutomationStatus, "automation_status_t")
