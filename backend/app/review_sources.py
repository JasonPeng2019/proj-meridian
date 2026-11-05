"""Resolve review citations against indexed evidence, never model-authored paths."""
from urllib.parse import urlparse


def source_record(store, name: str, *, detail=False):
    field = store.raw_fields.get(name, {})
    current = store.fields.get(name, field)
    owner = store.owners.get(name)
    row = next((row for key, row in store.rows.items() if name == key or name.startswith(key + "/")), None)
    if row:
        result = {"kind": "bom", "name": name, "label": f"{row.get('display_id', 'BOM')} / {row.get('display_name', row['name'])}",
                  "part_key": owner.get("key") if owner else None,
                  "source_path": field.get("source_path") or row.get("source_path"),
                  "source_row": field.get("source_row") or field.get("row") or row.get("source_row") or row.get("display_id")}
        if detail:
            result.update(row=row, original=field.get("original"), value=current.get("value"))
        return result
    if name.startswith("README/") and field:
        result = {"kind": "readme", "name": name, "label": field.get("title", name)}
        if detail:
            result["passage"] = field
        return result
    if name.endswith("/drawing/source"):
        owner = store.parts.get(name.split("/")[0])
    elif not ("/drawing/" in name and field):
        return None
    if not owner or not owner.get("drawing"):
        return None
    drawing = owner["drawing"]
    result = {"kind": "drawing", "name": name, "part_key": owner["key"], "page": field.get("page", 1),
              "box": field.get("box"), "label": f"{drawing['id']} / {name.split('/drawing/')[-1].replace('_', ' ')}",
              "source_path": drawing.get("source_path"), "source_filename": drawing.get("source_filename")}
    if detail:
        result.update(original=field.get("original", field.get("value")), value=current.get("value"))
    return result


def review_sources(store, item: dict) -> list[dict]:
    names = []
    seen = set()

    def add(name):
        if not isinstance(name, str) or name in seen:
            return
        seen.add(name)
        record = source_record(store, name)
        if record:
            names.append(record)
        # A computed dimension points to its actual printed dimension/callout.
        for cited in store.fields.get(name, {}).get("fact_ids", []):
            add(cited)

    add(item["target"])
    for reader in (item.get("readers") or {}).values():
        if not isinstance(reader, dict):
            continue
        for round_ in reader.get("rounds", [reader]):
            if round_.get("valid") is False or round_.get("validation_passed") is False:
                continue
            answer = round_.get("answer", round_)
            for name in answer.get("fact_ids", []):
                add(name)
    if not names and item.get("type") == "name_mapping":
        # Older receipts can lack citations. Expose exact name occurrences as
        # context, without presenting them as proof of a relationship.
        mapping = next((m for m in getattr(store, "mappings", []) if m["name"] == item["target"]), {})
        words = {str(mapping.get(side, "")).casefold() for side in ("left", "right")} - {""}
        for name, field in store.raw_fields.items():
            values = field.get("original", field.get("value"))
            values = values if isinstance(values, list) else [values]
            if any(str(value).casefold() in words for value in values):
                add(name)
    owner = store.owners.get(item["target"])
    if owner and owner.get("drawing"):
        if item["id"].startswith(("design:", "weight:")):
            for name, field in store.fields.items():
                if store.owners.get(name) is owner and ("/template/" in name or name.endswith(("/material", "/weight"))):
                    add(name)
        add(owner["drawing"]["id"] + "/drawing/source")
    for candidate in item.get("candidates", []):
        if isinstance(candidate, str):
            add(candidate)
    for example in (item.get("weight_check") or {}).get("examples", {}).values():
        for attempt in example.get("attempts", []):
            url = attempt.get("source_url", "")
            parsed = urlparse(url)
            if parsed.scheme in {"https", "http"} and parsed.netloc and url not in seen:
                seen.add(url)
                names.append({"name": url, "kind": "external", "url": url,
                              "label": "Density reference (outside source): " + attempt.get("source_title", parsed.netloc)})
    return names
