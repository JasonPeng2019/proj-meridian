import copy

import pytest

from scripts.verify_release import model_inventory


def manifest():
    return {
        did: {"examples": ["A", "B"], "template_sha256": did + "-template", "source_sha256": did + "-source",
              "generator_version": "flat-part-13", "models": {
                  name: {"template_sha256": did + "-template", "selections": {"thickness": thickness},
                         "step_sha256": "timestamp-dependent-export", "glb_sha256": "mesh"}
                  for name, thickness in (("A", 3), ("B", 6))}}
        for did in ("D-013", "D-025", "D-026", "D-014")}


@pytest.mark.parametrize("defect", ["missing_part", "stale_part", "missing_variant", "wrong_template", "wrong_generator", "wrong_selection"])
def test_release_inventory_detects_lost_or_changed_expansion_models(defect):
    original = manifest()
    shipped = copy.deepcopy(original)
    if defect == "missing_part":
        shipped.pop("D-014")
    elif defect == "stale_part":
        shipped["D-014"]["stale"] = True
    elif defect == "missing_variant":
        shipped["D-014"]["examples"] = ["A"]
        shipped["D-014"]["models"].pop("B")
    elif defect == "wrong_template":
        shipped["D-014"]["template_sha256"] = "different"
        for model in shipped["D-014"]["models"].values():
            model["template_sha256"] = "different"
    elif defect == "wrong_generator":
        shipped["D-014"]["generator_version"] = "older"
    else:
        shipped["D-014"]["models"]["B"]["selections"]["thickness"] = 7
    assert model_inventory(shipped) != model_inventory(original)


def test_release_inventory_allows_new_step_headers_but_preserves_template_identity():
    original = manifest()
    regenerated = copy.deepcopy(original)
    regenerated["D-014"]["models"]["A"]["step_sha256"] = "new-timestamp"
    assert model_inventory(regenerated) == model_inventory(original)
    regenerated["D-014"]["models"]["A"]["template_sha256"] = "wrong-template"
    with pytest.raises(AssertionError, match="different template"):
        model_inventory(regenerated)
