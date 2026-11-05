"""Install an already downloaded, remotely verified CAD release without CAD imports."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

from backend.paths import ROOT


def checked(base: Path, value: str | Path = ".") -> Path:
    """Reject traversal and links, including links which resolve inside the root."""
    base = Path(base).absolute()
    raw = str(value).replace("\\", "/")
    path = Path(raw)
    if PureWindowsPath(raw).drive and not path.is_absolute():
        raise ValueError("Foreign or drive-relative path is forbidden: " + raw)
    if ".." in PurePosixPath(raw).parts:
        raise ValueError("Traversal is forbidden: " + raw)
    path = path if path.is_absolute() else base / path
    if not path.absolute().is_relative_to(base):
        raise ValueError("Path escapes its allowed root: " + raw)
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise ValueError("Links are forbidden: " + str(item))
        if item == base:
            break
    resolved = path.resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ValueError("Path resolves outside its allowed root: " + raw)
    return resolved


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def structured_digest(path: Path) -> str:
    """Bind extracted drawing values independently of JSON layout/platform EOLs."""
    return hashlib.sha256(json.dumps(read(path), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decisions(root: Path) -> dict:
    directory = checked(root, "decisions")
    return {p.name: digest(checked(directory, p.name)) for p in sorted(directory.glob("*.json"))}


def effective_templates(root: Path) -> dict:
    # Store replays existing receipts and names fields; neither call builds CAD.
    from backend.app.store import Store
    store = Store(root)
    for part in store.records:
        template = store.templates.get((part.get("drawing") or {}).get("id"))
        if template is not None:
            template["bom_materials"] = [row["fields"]["material"] for row in part.get("bom", [])
                                         if row.get("fields", {}).get("material")]
    return store.templates


CAD_RECORD_KEYS = {"has_3d", "examples", "models", "model_manifest", "weight_check"}


def record_evidence(records):
    return [{key: value for key, value in row.items() if key not in CAD_RECORD_KEYS} for row in records]


def validate(artifact: Path, root: Path, candidate_batch: Path | None = None) -> dict:
    """Validate every input and export before preparing any live-file mutation."""
    from backend.cad import builder  # Only standard-library imports at module scope.
    from backend.cad.verification import selected_template
    artifact = checked(root, artifact)
    require(artifact.is_dir() and artifact != root, "Artifact must be a separate directory within the workspace")
    # Inspect even unused artifact paths: an archive with links is never trusted.
    for path in artifact.rglob("*"):
        checked(artifact, path)
    source = root
    checkpoint = None
    if candidate_batch is not None:
        batch = checked(root, candidate_batch)
        require(batch.is_relative_to(checked(root, "generated/ai_cache/detail-reprepare")), "Unexpected candidate batch location")
        checkpoint = read(checked(batch, "checkpoint.json"))
        require(checkpoint.get("complete") is True, "Candidate prep is incomplete")
        generated = checked(root, checkpoint["candidate"])
        require(generated == checked(batch, "candidate/generated"), "Candidate location differs from its batch")
        require(digest(checked(generated, "ai_results.json")) == checkpoint.get("candidate_sha256"), "Candidate AI data changed")
        for name, expected in checkpoint["source_hashes"].items():
            require(digest(checked(root, name)) == expected, "Candidate source changed: " + name)
        source = generated.parent
        require(decisions(source) == decisions(root), "Candidate decision snapshot differs from current receipts")
        for name in ("drawings.json", "bom.json", "readme.json"):
            require(digest(checked(source, "generated/" + name)) == digest(checked(root, "generated/" + name)),
                    "Candidate original evidence changed: " + name)
    inputs = read(checked(artifact, "docs/ci/cad-inputs.json"))
    current_inputs = {"ai_results_sha256": digest(checked(source, "generated/ai_results.json")),
                      "drawings_sha256": structured_digest(checked(root, "generated/drawings.json")),
                      "decisions": decisions(root), "generator_version": builder.VERSION}
    require(inputs == current_inputs, "Remote CAD input hashes differ from current inputs")
    require(digest(checked(artifact, "generated/ai_results.json")) == inputs["ai_results_sha256"], "Artifact AI data hash mismatch")
    require(structured_digest(checked(artifact, "generated/drawings.json")) == inputs["drawings_sha256"], "Artifact original drawings hash mismatch")
    cad = read(checked(artifact, "docs/ci/cad.json"))
    require(cad.get("passed") is True and cad.get("decisions_unchanged") is True, "Remote CAD verification did not pass")
    stages = read(checked(artifact, "docs/ci/browser-stages.json"))
    require(isinstance(stages, list) and len(stages) == 2 and
            {item.get("mode") for item in stages} == {"customer", "debug"} and
            all(item.get("passed") is True for item in stages), "Both browser stages must pass")
    browser = read(checked(artifact, "docs/verification/browser-check.json"))
    require(not browser.get("page_errors") and not browser.get("failed_responses"), "Browser verification contains failures")
    manifest = read(checked(artifact, "generated/models/manifest.json"))
    templates = effective_templates(source)
    require(set(manifest) == set(templates) == set(cad["expected_variants"]), "CAD manifest does not cover exactly the effective templates")
    drawings = read(checked(root, "generated/drawings.json"))
    payload = {}
    variants, rendered = set(), set()
    densities = read(checked(root, "backend/cad/densities.json"))
    for did, part in manifest.items():
        template = templates[did]
        template_hash = builder._hash(template)
        require(not part.get("stale"), did + ": stale reconstruction")
        require(part.get("generator_version") == builder.VERSION and part.get("template_sha256") == template_hash,
                did + ": model template/version mismatch")
        require(part.get("source_sha256") == template.get("source_sha256") == drawings[did]["sha256"], did + ": source provenance mismatch")
        models = part["models"]
        expected = cad["expected_variants"][did]
        try:
            eligible = list(builder._options(selected_template(template, {})))
            for option, _ in eligible:
                builder._validate_essential(option)
            eligible_count = len(eligible)
        except builder.Unknown:
            eligible_count = 0
        require(expected == eligible_count, did + ": report omits eligible variants")
        require(type(expected) is int and expected >= 0 and len(models) == expected, did + ": incomplete CAD variants")
        require(part["examples"] == list(models) == [chr(65 + n) for n in range(expected)], did + ": invalid variant inventory")
        if not models:
            require(bool(part.get("waiting")), did + ": unavailable template lacks a disposition")
            continue
        cache_key = builder._hash({"version": builder.VERSION, "template": template, "densities": densities})
        cache_rel = "generated/ai_cache/artifacts/cad/" + cache_key
        cached = read(checked(artifact, cache_rel + "/manifest.json"))
        clean = lambda value: {key: item for key, item in value.items() if key != "cache_hit"}
        require(clean(cached) == clean(part), did + ": cached CAD manifest mismatch")
        payload[cache_rel + "/manifest.json"] = checked(artifact, cache_rel + "/manifest.json")
        for variant, model in models.items():
            require(model.get("template_sha256") == template_hash, did + ": variant template mismatch")
            variants.add((did, variant))
            rendered.add((did, variant, model.get("glb_sha256")))
            for kind in ("glb", "step"):
                rel = model[kind]
                relative = PurePosixPath(str(rel).replace("\\", "/"))
                require(len(relative.parts) == 2 and relative.parts[0] == "models" and relative.suffix == "." + kind,
                        "Unexpected export path: " + str(rel))
                require(re.fullmatch(r"[A-Za-z0-9_.-]+", relative.name) is not None, "Invalid export filename")
                exported = checked(artifact, "generated/" + relative.as_posix())
                require(digest(exported) == model.get(kind + "_sha256"), did + ": export hash mismatch")
                cached_file = checked(artifact, cache_rel + "/" + relative.name)
                require(digest(cached_file) == model[kind + "_sha256"], did + ": cached export hash mismatch")
                require("generated/" + relative.as_posix() not in payload, "Duplicate model export path")
                payload["generated/" + relative.as_posix()] = exported
                payload[cache_rel + "/" + relative.name] = cached_file
    reported = [(item["part"], item["variant"]) for item in cad["variants"]]
    require(len(reported) == len(set(reported)) and set(reported) == variants and cad.get("variant_count") == len(variants), "CAD report variant set/count mismatch")
    require(cad.get("built_parts") == sum(bool(part["models"]) for part in manifest.values()), "CAD report part count mismatch")
    checked_models = [(item["drawing"], item["variant"], item["glb_sha256"]) for item in browser["models_rendered"]]
    require(len(checked_models) == len(set(checked_models)) and set(checked_models) == rendered, "Browser did not render exactly every verified GLB")
    if candidate_batch is not None:
        remote_records = read(checked(artifact, "generated/records.json"))
        require(record_evidence(remote_records) == record_evidence(read(checked(source, "generated/records.json"))), "Artifact records change candidate evidence")
        for row in remote_records:
            did = (row.get("drawing") or {}).get("id")
            part = manifest.get(did, {})
            require(row.get("models", {}) == part.get("models", {}) and row.get("model_manifest", {}) == part and
                    row.get("has_3d") == bool(part.get("models")) and row.get("examples", []) == part.get("examples", []) and
                    row.get("weight_check") == part.get("weight_check"), "Artifact record CAD projection mismatch")
        for rel in ("generated/ai_results.json", "generated/records.json", "generated/ai_cache/artifacts/ai_results.json"):
            payload[rel] = checked(artifact, rel)
        require(digest(payload["generated/ai_cache/artifacts/ai_results.json"]) == inputs["ai_results_sha256"], "Candidate AI cache mismatch")
    payload["generated/models/manifest.json"] = checked(artifact, "generated/models/manifest.json")
    # Validate every destination before the first preparation write.
    for rel in payload:
        checked(root, rel)
    return {"inputs": inputs, "payload": payload, "models": sorted(variants),
            "candidate": str(source.relative_to(root)) if checkpoint else None}


def install(artifact_dir: str | Path, run: str | int, candidate_batch: str | Path | None = None, *, root: Path = ROOT) -> dict:
    root = Path(root).resolve()
    require(re.fullmatch(r"[0-9]+", str(run)) is not None, "Actions run must be numeric")
    artifact = checked(root, artifact_dir)
    candidate = checked(root, candidate_batch) if candidate_batch is not None else None
    verified = validate(artifact, root, candidate)
    workspace = checked(root, ".runtime/cad-release/" + str(run))
    require(not workspace.exists(), "A release backup for this run already exists")
    workspace.mkdir(parents=True)
    staged, backups, applied = {}, {}, []
    for rel, source in verified["payload"].items():
        stage = checked(workspace, "prepared/" + rel)
        stage.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, stage)
        require(digest(stage) == digest(source), "Staged export changed during preparation")
        staged[rel] = stage
        target = checked(root, rel)
        backup = checked(workspace, "before/" + rel)
        if target.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target, backup)
            backups[rel] = backup
        else:
            backups[rel] = None
    lock = checked(root, "generated/.publish.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, (str(run) + "\n").encode())
        os.close(descriptor)
        descriptor = None
        # Recheck live receipts/input hashes and artifact bytes after staging.
        again = validate(artifact, root, candidate)
        require(again["inputs"] == verified["inputs"], "Inputs changed before publication")
        for rel, stage in staged.items():
            require(digest(stage) == digest(again["payload"][rel]), "Artifact changed before publication")
        for rel, stage in staged.items():  # manifest was inserted last
            target = checked(root, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage, target)
            applied.append(rel)
        report = {"schema_version": 1, "passed": True, "run": str(run),
                  "installed_at": datetime.now(timezone.utc).isoformat(), "inputs": verified["inputs"],
                  "candidate": verified["candidate"], "installed_models": [{"drawing": did, "variant": variant} for did, variant in verified["models"]],
                  "installed_files": {rel: digest(checked(root, rel)) for rel in staged},
                  "app_data_changed": any(backups[rel] is None or digest(backups[rel]) != digest(checked(root, rel)) for rel in staged),
                  "original_evidence_and_decisions_unchanged": True, "backup": workspace.relative_to(root).as_posix()}
        report_path = checked(root, "docs/verification/cad-install-" + str(run) + ".json")
        require(not report_path.exists(), "Install receipt already exists")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = checked(workspace, "install-receipt.json")
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, report_path)
        return report
    except BaseException:
        for rel in reversed(applied):
            target = checked(root, rel)
            if backups[rel] is None:
                target.unlink(missing_ok=True)
            else:
                replacement = checked(workspace, "rollback-" + uuid.uuid4().hex)
                shutil.copyfile(backups[rel], replacement)
                os.replace(replacement, target)
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("install")
    command.add_argument("artifact_dir", type=Path)
    command.add_argument("--run", required=True)
    command.add_argument("--candidate-batch", type=Path)
    args = parser.parse_args()
    report = install(args.artifact_dir, args.run, args.candidate_batch)
    print(json.dumps({"passed": report["passed"], "run": report["run"], "installed_models": len(report["installed_models"])}))


if __name__ == "__main__":
    main()
