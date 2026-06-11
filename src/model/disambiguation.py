NOT_A_QUESTION_MARKER = "NOT_A_QUESTION"


def is_business_question(sql_or_marker: str) -> bool:
    """Return False if the LLM flagged the input as not a valid business question."""
    return sql_or_marker.strip() != NOT_A_QUESTION_MARKER
