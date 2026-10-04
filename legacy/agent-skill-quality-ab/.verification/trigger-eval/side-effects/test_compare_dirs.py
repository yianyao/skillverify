# -*- coding: utf-8 -*-
"""compare_dirs.py 的单元测试。"""
import sys
from pathlib import Path

import pytest

import compare_dirs


# ---------- list_files ----------

class TestListFiles:
    def test_empty_dir_returns_empty_dict(self, tmp_path):
        assert compare_dirs.list_files(tmp_path) == {}

    def test_nested_files_use_posix_relative_keys(self, tmp_path):
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        deep = tmp_path / "sub" / "deep"
        deep.mkdir(parents=True)
        (deep / "b.txt").write_text("y", encoding="utf-8")
        files = compare_dirs.list_files(tmp_path)
        assert set(files) == {"a.txt", "sub/deep/b.txt"}
        assert files["a.txt"] == str(tmp_path / "a.txt")

    def test_missing_root_returns_empty_dict(self, tmp_path):
        assert compare_dirs.list_files(tmp_path / "no_such_dir") == {}

    def test_directories_are_not_listed(self, tmp_path):
        (tmp_path / "empty_dir").mkdir()
        assert compare_dirs.list_files(tmp_path) == {}


# ---------- is_binary ----------

class TestIsBinary:
    @pytest.mark.parametrize(
        "data,expected",
        [
            (b"", False),                       # 空数据
            (b"plain text\n", False),           # 纯文本
            (b"\x00", True),                    # 开头就是 NUL
            (b"abc\x00def", True),              # 中间有 NUL
            (b"a" * 8191 + b"\x00", True),      # NUL 恰好在第 8192 字节（切片内最后一个）
            (b"a" * 8192 + b"\x00", False),     # NUL 在第 8193 字节，超出检测窗口
        ],
    )
    def test_detection_window(self, data, expected):
        assert compare_dirs.is_binary(data) is expected


# ---------- main（端到端，基于临时目录） ----------

def run_main(monkeypatch, capsys, dir_a, dir_b, output, extra=()):
    argv = ["compare_dirs.py", str(dir_a), str(dir_b), "-o", str(output), *extra]
    monkeypatch.setattr(sys, "argv", argv)
    compare_dirs.main()
    out = capsys.readouterr().out
    report = Path(output).read_text(encoding="utf-8")
    return out, report


class TestMain:
    def test_missing_dir_exits_with_error(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(
            sys, "argv", ["compare_dirs.py", str(tmp_path), str(tmp_path / "nope")]
        )
        with pytest.raises(SystemExit) as excinfo:
            compare_dirs.main()
        assert excinfo.value.code == 1
        assert "目录不存在" in capsys.readouterr().err

    def test_identical_files_no_diff_section(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        (d1 / "f.txt").write_text("same\n", encoding="utf-8")
        (d2 / "f.txt").write_text("same\n", encoding="utf-8")
        out, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        assert "共有文件: 1 | 仅在 A: 0 | 仅在 B: 0" in report
        assert "文件不同" not in report
        assert "总结: 共 1 个同名文件，其中 0 个内容不同。" in report

    def test_text_file_diff(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        (d1 / "f.txt").write_text("line1\nline2\n", encoding="utf-8")
        (d2 / "f.txt").write_text("line1\nline3\n", encoding="utf-8")
        out, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        assert "## 文件不同: f.txt" in report
        assert "-line2" in report
        assert "+line3" in report
        assert "A/f.txt" in report and "B/f.txt" in report
        assert "总结: 共 1 个同名文件，其中 1 个内容不同。" in report

    def test_empty_file_vs_text_file_counts_as_diff(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        (d1 / "f.txt").write_text("", encoding="utf-8")
        (d2 / "f.txt").write_text("new\n", encoding="utf-8")
        _, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        assert "## 文件不同: f.txt" in report
        assert "+new" in report

    def test_files_only_in_a_or_b(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        (d1 / "common.txt").write_text("x\n", encoding="utf-8")
        (d2 / "common.txt").write_text("x\n", encoding="utf-8")
        (d1 / "a_only.txt").write_text("", encoding="utf-8")
        (d2 / "b_only.txt").write_text("", encoding="utf-8")
        _, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        assert "共有文件: 1 | 仅在 A: 1 | 仅在 B: 1" in report
        assert "## 仅存在于目录 A 的文件:" in report
        assert "  - a_only.txt" in report
        assert "## 仅存在于目录 B 的文件:" in report
        assert "  - b_only.txt" in report

    def test_common_file_in_subdirectory(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        (d1 / "sub").mkdir(parents=True)
        (d2 / "sub").mkdir(parents=True)
        (d1 / "sub" / "x.txt").write_text("old\n", encoding="utf-8")
        (d2 / "sub" / "x.txt").write_text("new\n", encoding="utf-8")
        _, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        assert "共有文件: 1" in report
        assert "## 文件不同: sub/x.txt" in report

    def test_binary_diff_is_not_line_diffed(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        (d1 / "bin.dat").write_bytes(b"\x00\x01\x02")
        (d2 / "bin.dat").write_bytes(b"\x00\x01\x03")
        _, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        assert "## 文件不同: bin.dat" in report
        assert "[二进制文件] 内容不同，跳过逐行 diff。" in report
        assert "-\x00" not in report  # 不会对二进制做逐行 diff

    def test_gbk_encoded_text_still_diffed(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        (d1 / "gbk.txt").write_bytes("你好\n世界\n".encode("gbk"))
        (d2 / "gbk.txt").write_bytes("你好\n世变\n".encode("gbk"))
        _, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        assert "## 文件不同: gbk.txt" in report
        assert "[无法解码]" not in report
        assert "-世界" in report and "+世变" in report

    def test_undecodable_bytes_reported(self, tmp_path, monkeypatch, capsys):
        # b"\x81\x25"：既不是合法 UTF-8，也不是合法 GBK，且无 NUL（不被判为二进制）
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        (d1 / "junk.bin").write_bytes(b"\x81\x25" * 20)
        (d2 / "junk.bin").write_bytes(b"\x81\x27" * 20)
        _, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        assert "[无法解码] 非 UTF-8/GBK 文本，跳过 diff。" in report
        assert "其中 1 个内容不同" in report

    def test_empty_dirs(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        _, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "r.txt")
        assert "共有文件: 0 | 仅在 A: 0 | 仅在 B: 0" in report
        assert "总结: 共 0 个同名文件，其中 0 个内容不同。" in report

    def test_report_written_and_printed(self, tmp_path, monkeypatch, capsys):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        (d1 / "f.txt").write_text("a\n", encoding="utf-8")
        (d2 / "f.txt").write_text("a\n", encoding="utf-8")
        out, report = run_main(monkeypatch, capsys, d1, d2, tmp_path / "custom.txt")
        out_path = tmp_path / "custom.txt"
        assert out_path.exists()
        assert out.startswith(report)  # 终端先打印完整报告，再打印写入路径
        assert "报告已写入" in out
        assert report.startswith("=" * 60)
        assert report.endswith("\n")
