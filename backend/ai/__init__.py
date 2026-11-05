"""Offline evidence preparation; paid readers are never needed for normal launch."""

def run_prep(*args, **kwargs):
    from .pipeline import run_prep as run
    return run(*args, **kwargs)
