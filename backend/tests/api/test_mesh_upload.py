"""VTK / CGNS uploads.

Reported: a standard legacy-ASCII .vtk failed with "No module named 'pyvista'".
The reader now uses plain VTK (`vtk` in requirements.txt, no pyvista), and when
VTK is missing a text mesh still reaches the AI-written-reader path while a
binary one gets a clear "install VTK" message instead of a raw ModuleNotFoundError.
"""
from __future__ import annotations

import pytest

from app.api import datasets as datasets_api
from app.services.datasets import mesh_reader_available

_ASCII_VTK = b"""# vtk DataFile Version 3.0
tiny
ASCII
DATASET POLYDATA
POINTS 3 float
0 0 0
1 0 0
0 1 0
POINT_DATA 3
SCALARS p float 1
LOOKUP_TABLE default
1.0 2.0 3.0
VECTORS U float
1 0 0
0 1 0
0 0 1
"""

# Cell-centred field only (typical CFD export): must be carried to the points.
_CELL_ONLY_VTK = b"""# vtk DataFile Version 3.0
cells
ASCII
DATASET UNSTRUCTURED_GRID
POINTS 4 float
0 0 0
1 0 0
1 1 0
0 1 0
CELLS 1 5
4 0 1 2 3
CELL_TYPES 1
9
CELL_DATA 1
SCALARS T float 1
LOOKUP_TABLE default
300.0
"""

_BINARY_VTK = (b"# vtk DataFile Version 3.0\ntiny\nBINARY\nDATASET POLYDATA\nPOINTS 3 float\n"
               + b"\x00\x00\x80\x3f" * 9)

needs_vtk = pytest.mark.skipif(not mesh_reader_available(), reason="vtk not installed")


def _up(client, user, name, data):
    return client.post("/api/datasets", headers=user["h"],
                       files={"file": (name, data, "application/octet-stream")})


@needs_vtk
def test_ascii_vtk_is_read_natively(client, alice):
    r = _up(client, alice, "tiny.vtk", _ASCII_VTK)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["dataset"]["rows"] == 3
    for col in ("X", "Y", "Z", "p", "U_x", "U_y", "U_z"):
        assert f'"{col}"' in r.text, col


@needs_vtk
def test_cell_only_field_is_moved_to_points(client, alice):
    r = _up(client, alice, "cells.vtk", _CELL_ONLY_VTK)
    assert r.status_code == 200, r.text
    assert r.json()["dataset"]["rows"] == 4
    assert "T" in r.text


def test_without_vtk_ascii_falls_back_to_generic_parser(client, alice, monkeypatch):
    monkeypatch.setattr(datasets_api, "mesh_reader_available", lambda: False)
    r = _up(client, alice, "tiny.vtk", _ASCII_VTK)
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("needs_parser", "ok")
    assert "ModuleNotFoundError" not in r.text


def test_without_vtk_binary_says_vtk_is_needed(client, alice, monkeypatch):
    monkeypatch.setattr(datasets_api, "mesh_reader_available", lambda: False)
    r = _up(client, alice, "tiny.vtk", _BINARY_VTK)
    assert r.status_code == 400
    assert "VTK" in r.json()["detail"]
    assert "ModuleNotFoundError" not in r.text
