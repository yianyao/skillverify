# -*- coding: utf-8 -*-
"""diff_folders.py 的单元测试。"""
import sys
from pathlib import Path

import pytest

import diff_folders


# ---------- collect_files ----------

class TestCollectFiles:
    def test_empty_folder(self, tmp_path):
        assert diff_folders.collect_files(tmp_path, recursive=False) == {}
        assert diff_folders.collect_files(tmp_path, recursive=True) == {}

    def test_nonrecursive_ignores_subdirectories(self, tmp_path):
        (tmp_path / "top.txt").write_text("x", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "inner.txt").write_text("y", encoding="utf-8")
        files = diff_folders.collect_files(tmp_path, recursive=False)
        assert set(files) == {"top.txt"}

    def test_recursive_includes_subdirectories(self, tmp_path):
        (tmp_path / "top.txt").write_text("x", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "inner.txt").write_text("y", encoding="utf-8")
        files = diff_folders.collect_files(tmp_path, recursive=True)
        assert set(files) == {"top.txt", "sub/inner.txt"}
        assert files["sub/inner.txt"] == sub / "inner.txt"

    def test_directories_are_never_collected(self, tmp_path):
        (tmp_path / "empty_dir").mkdir()
        (tmp_path / "nested" / "deeper").mkdir(parents=True)
        assert diff_folders.collect_files(tmp_path, recursive=False) == {}
        assert diff_folders.collect_files(tmp_path, recursive=True) == {}


# ---------- read_text ----------

class TestReadText:
    def test_valid_utf8(self, tmp_path):
        p = tmp_path / "t.txt"
        p.write_text("héllo\n", encoding="utf-8")
        assert diff_folders.read_text(p) == "héllo\n"

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.txt"
        p.write_text("", encoding="utf-8")
        assert diff_folders.read_text(p) == ""

    def test_invalid_utf8_returns_replacement_text_not_none(self, tmp_path):
        p = tmp_path / "bad.txt"
        p.write_bytes(b"\xff\xfe abc")
        text = diff_folders.read_text(p)
        assert text is not None
        assert "\ufffd" in text  # errors="replace" 生效

    def test_missing_file_returns_none_with_warning(self, tmp_path, capsys):
        missing = tmp_path / "missing.txt"
        assert diff_folders.read_text(missing) is None
        err = capsys.readouterr().err
        assert "[警告] 无法读取" in err
        assert "missing.txt" in err


# ---------- main（端到端，基于临时目录） ----------

def run_main(monkeypatch, capsys, dir_a, dir_b, output, extra=()):
    argv = ["diff_folders.py", str(dir_a), str(dir_b), "-o", str(output), *extra]
    monkeypatch.setattr(sys, "argv", argv)
    diff_folders.main()
    out = capsys.readouterr().out
    report = Path(output).read_text(encoding="utf-8")
    return out, report


class TestMain:
    def test_missing_dir_b_exits(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(
            sys, "argv", ["diff_folders.py", str(tmp_path), str(tmp_path / "nope")]
        )
        with pytest.raises(SystemExit) as excinfo:
            diff_folders.main()
        assert excinfo.value.code == 1
        assert "[错误]" in capsys.readouterr().err

    def test_identical_files_counted_same(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        (d1 / "f.txt").write_text("same\n", encoding="utf-8")
        (d2 / "f.txt").write_text("same\n", encoding="utf-8")
        _, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        assert "[差异]" not in report
        assert "统计: 相同 1 | 有差异 0 | 仅 A 0 | 仅 B 0" in report

    def test_text_diff_headers_and_lines(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        (d1 / "f.txt").write_text("a\nb\nc\n", encoding="utf-8")
        (d2 / "f.txt").write_text("a\nx\nc\n", encoding="utf-8")
        _, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        assert "[差异] f.txt" in report
        assert "A/f.txt" in report and "B/f.txt" in report
        assert "-b" in report and "+x" in report
        assert "统计: 相同 0 | 有差异 1 | 仅 A 0 | 仅 B 0" in report

    def test_empty_file_vs_text_file_is_diff(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        (d1 / "f.txt").write_text("", encoding="utf-8")
        (d2 / "f.txt").write_text("new\n", encoding="utf-8")
        _, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        assert "[差异] f.txt" in report
        assert "+new" in report

    def test_unreadable_file_is_skipped(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        (d1 / "bad.txt").write_text("x\n", encoding="utf-8")
        (d2 / "bad.txt").write_text("y\n", encoding="utf-8")
        (d1 / "good.txt").write_text("z\n", encoding="utf-8")
        (d2 / "good.txt").write_text("z\n", encoding="utf-8")
        orig = diff_folders.read_text

        def fake_read_text(path):
            if "bad.txt" in str(path):
                return None  # 模拟 OSError 路径
            return orig(path)

        monkeypatch.setattr(diff_folders, "read_text", fake_read_text)
        _, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        assert "[跳过] bad.txt (无法按文本读取)" in report
        assert "统计: 相同 1 | 有差异 0 | 仅 A 0 | 仅 B 0" in report

    def test_nonrecursive_subdir_file_is_invisible(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        (d1 / "top.txt").write_text("x\n", encoding="utf-8")
        (d2 / "top.txt").write_text("x\n", encoding="utf-8")
        sub = d1 / "sub"
        sub.mkdir()
        (sub / "x.txt").write_text("only in A\n", encoding="utf-8")
        _, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        # 非递归模式下子目录文件完全不可见，而不是计入"仅 A"
        assert "共  1 个同名文件, 仅 A 有 0 个, 仅 B 有 0 个" in report
        assert "sub/x.txt" not in report

    def test_recursive_matches_subdir_file(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        (d1 / "sub").mkdir(parents=True)
        (d2 / "sub").mkdir(parents=True)
        (d1 / "sub" / "x.txt").write_text("old\n", encoding="utf-8")
        (d2 / "sub" / "x.txt").write_text("new\n", encoding="utf-8")
        _, report = run_main(
            monkeypatch, capsys, d1, d2, tmp_path / "r.txt", extra=["-r"]
        )
        assert "共  1 个同名文件" in report
        assert "[差异] sub/x.txt" in report

    def test_context_zero_removes_context_lines(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        content_a = "a\nb\nc\nd\ne\nf\n"
        content_b = "a\nb\nX\nd\ne\nf\n"
        (d1 / "f.txt").write_text(content_a, encoding="utf-8")
        (d2 / "f.txt").write_text(content_b, encoding="utf-8")

        _, report_ctx0 = run_main(
            monkeypatch, capsys, d1, d2, tmp_path / "r0.txt", extra=["--context", "0"]
        )
        _, report_default = run_main(
            monkeypatch, capsys, d1, d2, tmp_path / "r3.txt", extra=[]
        )
        ctx0_lines = [l for l in report_ctx0.splitlines() if l.startswith(" ")]
        assert ctx0_lines == []  # 上下文为 0 时无 " " 前缀的上下文行
        assert any(l.startswith(" ") for l in report_default.splitlines())

    def test_only_in_sections(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        (d1 / "a_only.txt").write_text("", encoding="utf-8")
        (d2 / "b_only.txt").write_text("", encoding="utf-8")
        _, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        assert "仅在 A 中存在 (1):" in report and "  - a_only.txt" in report
        assert "仅在 B 中存在 (1):" in report and "  - b_only.txt" in report
        assert "统计: 相同 0 | 有差异 0 | 仅 A 1 | 仅 B 1" in report

    def test_report_file_written(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        _, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "custom.txt")
        out_path = tmp_path / "custom.txt"
        assert out_path.exists()
        assert report.startswith("=" * 70)
        assert report.endswith("\n")
        assert "统计:" in report
