"""Filename parsing and reference-reading tests."""

from pathlib import Path

from aqfilter.naming import parse_name, parse_or_unknown, read_refs


def test_parse_valid_name():
    parsed = parse_name("Abdul_Basit_Murattal_192kbps_001007.mp3")
    assert parsed == {
        "reciter": "Abdul_Basit_Murattal",
        "kbps_label": 192,
        "surah": 1,
        "ayah": 7,
    }


def test_parse_invalid_name():
    assert parse_name("not_a_recitation.mp3") is None
    assert parse_name("Abdul_Basit_Murattal_192kbps_001007.wav") is None
    unknown = parse_or_unknown("garbage.mp3")
    assert unknown["reciter"] == "UNKNOWN"


def test_read_refs_text_file(tmp_path: Path):
    refs = tmp_path / "refs.txt"
    refs.write_text(
        "# comment\n\nHusary_128kbps_008016.mp3\nsome/dir/Hudhaify_128kbps_026044.mp3\n",
        encoding="utf-8",
    )
    assert read_refs(refs) == [
        "Hudhaify_128kbps_026044.mp3",
        "Husary_128kbps_008016.mp3",
    ]


def test_read_refs_csv(tmp_path: Path):
    refs = tmp_path / "refs.csv"
    refs.write_text("filename\nHusary_128kbps_008016.mp3\n", encoding="utf-8")
    assert read_refs(refs) == ["Husary_128kbps_008016.mp3"]


def test_read_refs_directory(tmp_path: Path):
    (tmp_path / "AB").mkdir()
    (tmp_path / "HUS").mkdir()
    (tmp_path / "AB" / "Abdul_Basit_Murattal_192kbps_003180.mp3").write_bytes(b"x")
    (tmp_path / "HUS" / "Husary_128kbps_008016.mp3").write_bytes(b"x")
    assert read_refs(tmp_path) == [
        "Abdul_Basit_Murattal_192kbps_003180.mp3",
        "Husary_128kbps_008016.mp3",
    ]
