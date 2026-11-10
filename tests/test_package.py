import importlib

STAGES = ["contracts", "db", "intake", "understand", "decide", "review", "pipeline", "workers"]


def test_package_version():
    import flag_it

    assert flag_it.__version__ == "0.1.0"


def test_every_stage_folder_imports():
    for stage in STAGES:
        importlib.import_module(f"flag_it.{stage}")
