from app.modules.classroom.schemas import AuthorizationAction

CALLER_ALLOWED_ACTIONS: dict[str, frozenset[AuthorizationAction]] = {
    "document": frozenset(
        {
            AuthorizationAction.DOCUMENT_READ,
            AuthorizationAction.DOCUMENT_SHARE,
            AuthorizationAction.DOCUMENT_MANAGE,
        }
    ),
    "ai": frozenset({AuthorizationAction.AI_QUERY}),
    "learning": frozenset(
        {
            AuthorizationAction.PRACTICE_ACCESS,
            AuthorizationAction.ASSIGNMENT_CREATE,
            AuthorizationAction.ASSIGNMENT_SUBMIT,
            AuthorizationAction.ASSESSMENT_MANAGE,
            AuthorizationAction.GRADE_MANAGE,
            AuthorizationAction.ANALYTICS_VIEW,
        }
    ),
}


def service_may_authorize(service_id: str, action: AuthorizationAction) -> bool:
    """Restrict each trusted service identity to its documented action set."""
    return action in CALLER_ALLOWED_ACTIONS.get(service_id, frozenset())
