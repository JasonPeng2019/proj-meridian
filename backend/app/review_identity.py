"""Present authorized reviews under the reviewer's authority without editing receipts."""


def presented_review(record):
    if not isinstance(record, dict) or record.get("review_kind") != "delegated":
        return record
    result = dict(record)
    principal = record.get("delegated_by") or record.get("display_by", "").removesuffix(" - delegated review") or record.get("by")
    result.update(by=principal, display_by=principal)
    return result
