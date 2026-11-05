"""Separate unresolved engineering input from oversight of an AI answer."""

RESOLVED = {"accepted", "rejected", "human_confirmed", "human_rejected", "approved", "reviewed"}


def classify_review(item: dict) -> tuple[str, str]:
    if item.get("status") in RESOLVED:
        return "resolved", "A human decision is already recorded."
    if item.get("input_reason"):
        return "human_input", item["input_reason"]
    kind = item.get("type")
    if kind == "weight":
        return "human_input", "The weight check needs a human explanation or corrected inputs."
    if kind == "link":
        return "human_input", "The pipeline could not resolve the drawing-to-parts-list match."
    if kind == "possible_reading" or item.get("state") == "options":
        return "human_input", "Several readings remain possible; a person must resolve the ambiguity."
    if kind == "template" or item.get("state") == "unknown" or item.get("method") in {"ai_unsure", "unresolved"}:
        return "human_input", "The pipeline could not determine this input reliably."
    if item.get("id", "").startswith("design:"):
        return "human_review", "The AI reconstruction is ready for human oversight."
    if kind not in {"correction", "source_changed"} and item.get("value") is None:
        return "human_input", "There is no resolved value for a person to review."
    return "human_review", "A proposed answer is available; human review is still outstanding."
