"""Resolve review citations against indexed evidence, never model-authored paths."""
from urllib.parse import urlparse


def source_record(store, name: str, *, detail=False):
    field = store.raw_fields.get(name, {})
    current = store.fields.get(name, field)
    owner = store.owners.get(name)
    row = next((row for key, row in store.rows.items() if name == key or name.startswith(key + "/")), None) if name.startswith("BOM:") else None
    if row:
        if name != row["name"] and name not in store.fields and not any(f.get("name") == name for f in row.get("fields", {}).values()):
            return None
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


def review_readers(readers: dict) -> dict:
    """Keep displayed original answers without duplicating hidden raw feedback."""
    result = {}
    for name, reader in (readers or {}).items():
        if not isinstance(reader, dict):
            continue
        rounds = []
        for raw in reader.get("rounds") or [reader]:
            if not isinstance(raw, dict) or raw.get("requested") is False:
                continue
            answer = raw.get("answer", raw)
            answer = ({key: answer[key] for key in (
                "key", "state", "value", "value_json", "confidence", "fact_ids", "reason",
                "changed_because", "decision", "repairable") if key in answer} if isinstance(answer, dict) else None)
            rounds.append({**{key: raw[key] for key in (
                "valid", "validation_passed", "requested", "proposal_fingerprint",
                "response_proposal_fingerprint", "contract_error") if key in raw}, "answer": answer})
        result[name] = {**{key: reader[key] for key in ("role", "protocol") if key in reader}, "rounds": rounds}
    return result


def review_sources(store, item: dict, *, cache: dict | None = None) -> list[dict]:
    names = []
    seen = set()

    def add(name):
        if not isinstance(name, str) or name in seen:
            return
        seen.add(name)
        if cache is None:
            record = source_record(store, name)
        else:
            if name not in cache:
                cache[name] = source_record(store, name)
            record = cache[name]
        if record:
            names.append(record)
        # A computed dimension points to its actual printed dimension/callout.
        for cited in store.fields.get(name, {}).get("fact_ids") or []:
            add(cited)

    add(item["target"])
    for reader in (item.get("readers") or {}).values():
        if not isinstance(reader, dict):
            continue
        for round_ in reader.get("rounds") or [reader]:
            if not isinstance(round_, dict) or round_.get("valid") is False or round_.get("validation_passed") is False:
                continue
            answer = round_.get("answer", round_)
            if not isinstance(answer, dict):
                continue
            for name in answer.get("fact_ids") or []:
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
    for candidate in item.get("candidates") or []:
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
