import json
import threading
import time

import pytest

from app.domain.models import Horizon, Scenario
from app.services.climate import ChelsaCogProvider


# This test also serves as the CI trigger for the fix/** validation branch.
def test_parallel_point_profile_preserves_member_medians(tmp_path, monkeypatch):
    variable_names = ["bio01", "bio05", "bio06", "bio12", "bio15"]
    members = []
    expected = {}
    for member_index, model in enumerate(["m1", "m2", "m3"]):
        variables = {}
        for variable_index, variable in enumerate(variable_names):
            key = f"{model}-{variable}"
            variables[variable] = {
                "path": key,
                "unit": "x",
                "scale": 1.0,
                "offset": 0.0,
            }
            expected[key] = float(variable_index * 100 + member_index * 10)
        members.append({"model": model, "variables": variables})

    node = {"period": "2041-2070", "scenario": "ssp370", "members": members}
    profiles = {
        horizon.value: {scenario.value: dict(node) for scenario in Scenario}
        for horizon in Horizon
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"profiles": profiles}), encoding="utf-8")
    provider = ChelsaCogProvider(str(manifest))

    threads = set()
    lock = threading.Lock()

    def fake_sample(spec, longitude, latitude):
        with lock:
            threads.add(threading.current_thread().name)
        time.sleep(0.01)
        return expected[spec["path"]]

    monkeypatch.setattr(provider, "_sample", fake_sample)
    result = provider.profile(47.16, -1.27, Horizon.Y2050, Scenario.MEDIUM)

    for variable_index, variable in enumerate(variable_names):
        assert result.variables[variable] == pytest.approx(variable_index * 100 + 10.0)
        assert result.uncertainty[variable].n == 3
    assert len(threads) >= 2
