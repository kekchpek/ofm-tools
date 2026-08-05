"""Core transfer tests."""

from __future__ import annotations

import shutil

from core.transfer import transfer_metadata_files


def test_transfer_video6(tmp_media, video6_target, video6_source):
    destination = tmp_media / "video6_with_metadata.mov"
    output = transfer_metadata_files(video6_target, video6_source, destination)
    assert output.is_file()
    assert output.stat().st_size > video6_target.stat().st_size


def test_transfer_heic(tmp_media, heic_source, video6_source):
    if not heic_source.exists():
        return
    target = tmp_media / "target.heic"
    shutil.copy2(heic_source, target)
    destination = tmp_media / "avatar_with_metadata.heic"
    output = transfer_metadata_files(target, heic_source, destination)
    assert output.is_file()
