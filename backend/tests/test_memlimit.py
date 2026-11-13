"""The instance's memory limit is read from the container, not remembered."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import memlimit  # noqa: E402


def _file(tmp_path, text):
    p = tmp_path / "memory.max"
    p.write_text(text)
    return str(p)


def test_the_containers_own_limit_is_used(tmp_path):
    assert memlimit.detect(paths=(_file(tmp_path, str(2 * 1024 ** 3) + "\n"),), env={}) == (2048, "container limit")


def test_a_setting_made_on_purpose_wins(tmp_path):
    assert memlimit.detect(paths=(_file(tmp_path, str(2 * 1024 ** 3)),), env={"MEM_LIMIT_MB": "1024"}) == (1024, "MEM_LIMIT_MB")


def test_no_limit_or_no_file_falls_back(tmp_path):
    assert memlimit.detect(paths=(_file(tmp_path, "max"),), env={}) == (512, "default")
    assert memlimit.detect(paths=(_file(tmp_path, str(2 ** 63 - 4096)),), env={}) == (512, "default")
    assert memlimit.detect(paths=("/no/such/file",), env={"MEM_LIMIT_MB": "junk"}) == (512, "default")
