import numpy as np
import pytest

from harborvision.vision import _write_image


def test_evidence_image_write_failure_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr("harborvision.vision.cv2.imwrite", lambda *_args: False)
    with pytest.raises(RuntimeError, match="could not write evidence image"):
        _write_image(tmp_path / "evidence.jpg", np.zeros((8, 8, 3), dtype=np.uint8))
