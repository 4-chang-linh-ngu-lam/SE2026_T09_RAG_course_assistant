"""Bounded source coordinates for a supplied nonlinear sampling mesh.

This diagnostic maps prepared pixel centres back to source pixel centres.
It does not load a model, render/replace an image, certify source coverage,
invert the mesh, establish OCR correctness or grant publication trust.
"""
from __future__ import annotations

import numpy as np

DENSE_SAMPLING_VERSION = "idp-dense-sampling-1"


def _numeric_array(value, *, max_values):
    try:
        array = np.asarray(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid numeric coordinates") from exc
    if array.dtype.kind not in "fiu":
        raise ValueError("coordinates must be real numbers")
    if array.size > max_values:
        raise ValueError("numeric coordinates exceed work limit")
    array = array.astype(np.float64)
    if not np.isfinite(array).all():
        raise ValueError("nonfinite coordinates")
    return array


def _image_size(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(type(v) is not int or not 2 <= v <= 10000 for v in value)
            or value[0] * value[1] > 16_000_000):
        raise ValueError("invalid bounded image size")
    return tuple(value)


class SamplingGrid:
    """A normalized backward mesh using bilinear align_corners=True semantics.

    Mesh axes are HxWx2, or the explicit model layout1x2xHxW. Coordinates
    (-1,-1)/(1,1) refer to source pixel centres (0,0)/(W-1,H-1). Prepared
    centre coordinates span the same normalized domain on the mesh.
    """

    def __init__(self, mesh, source_size, prepared_size):
        grid = _numeric_array(mesh, max_values=16384)
        if grid.ndim == 4 and grid.shape[:2] == (1, 2):
            grid = grid[0].transpose(1, 2, 0)
        if (grid.ndim != 3 or grid.shape[2] != 2 or min(grid.shape[:2]) < 2
                or grid.shape[0] * grid.shape[1] > 8192 or np.abs(grid).max() > 10000):
            raise ValueError("invalid bounded sampling mesh")
        self._grid = grid.copy()
        self._grid.setflags(write=False)
        self.source_size = _image_size(source_size)
        self.prepared_size = _image_size(prepared_size)

    def map_centres(self, points):
        """Return source float coordinates without clipping/padding repair."""
        points = _numeric_array(points, max_values=65536)
        if points.shape == (0,):
            points = points.reshape(0, 2)
        if points.ndim != 2 or points.shape[1] != 2 or len(points) > 32768:
            raise ValueError("invalid or excessive prepared points")
        width, height = self.prepared_size
        if (np.any(points < 0) or np.any(points[:, 0] > width - 1)
                or np.any(points[:, 1] > height - 1)):
            raise ValueError("point outside prepared pixel-centre domain")
        gh, gw = self._grid.shape[:2]
        u = points[:, 0] * (gw - 1) / (width - 1)
        v = points[:, 1] * (gh - 1) / (height - 1)
        x = np.minimum(np.floor(u).astype(int), gw - 2)
        y = np.minimum(np.floor(v).astype(int), gh - 2)
        a, b = (u - x)[:, None], (v - y)[:, None]
        normalized = ((1 - a) * (1 - b) * self._grid[y, x]
                      + a * (1 - b) * self._grid[y, x + 1]
                      + (1 - a) * b * self._grid[y + 1, x]
                      + a * b * self._grid[y + 1, x + 1])
        return (normalized + 1) * np.array([self.source_size[0] - 1,
                                          self.source_size[1] - 1]) / 2

    def source_support_bbox(self, box, *, source_error_pixels=0.):
        """Conservative contributing-source envelope for an integer pixel ROI.

        box is half-open in prepared pixels. Evaluate its centre-domain boundary
        AND every interior mesh knot: four corners alone can miss an interior
        extremum of a nonlinear map. Bilinear source-pixel neighbours are included.
        Outside-source samples are padding, not invented source coordinates.
        None means the envelope has no possible in-frame source contribution.
        This describes the mathematical mesh; a renderer's validated numerical
        error bound can be supplied explicitly in source pixels. It does not
        establish that any supplied prepared image was rendered from this mesh.
        """
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or any(type(v) is not int for v in box)):
            raise ValueError("integer half-open prepared pixel box required")
        left, top, right, bottom = box
        width, height = self.prepared_size
        if not 0 <= left < right <= width or not 0 <= top < bottom <= height:
            raise ValueError("box outside prepared pixels")
        if (type(source_error_pixels) not in (int, float)
                or not np.isfinite(source_error_pixels) or not 0 <= source_error_pixels <= 1):
            raise ValueError("invalid source precision allowance")
        gh, gw = self._grid.shape[:2]
        xs = np.arange(gw) * (width - 1) / (gw - 1)
        ys = np.arange(gh) * (height - 1) / (gh - 1)
        xs = np.unique(np.r_[left, right - 1, xs[(xs > left) & (xs < right - 1)]])
        ys = np.unique(np.r_[top, bottom - 1, ys[(ys > top) & (ys < bottom - 1)]])
        xx, yy = np.meshgrid(xs, ys)
        mapped = self.map_centres(np.c_[xx.ravel(), yy.ravel()])
        low = np.maximum(np.floor(mapped.min(axis=0) - source_error_pixels).astype(int), 0)
        high = np.minimum(np.ceil(mapped.max(axis=0) + source_error_pixels).astype(int) + 1,
                          self.source_size)
        if np.any(high <= low):
            return None
        return [int(low[0]), int(low[1]), int(high[0]), int(high[1])]

    def diagnostics(self):
        grid = self._grid
        a, b, c, d = grid[:-1, :-1], grid[:-1, 1:], grid[1:, :-1], grid[1:, 1:]
        def cross(u, v):
            return u[..., 0] * v[..., 1] - u[..., 1] * v[..., 0]
        jacobians = np.stack([cross(b-a, c-a), cross(b-a, d-b),
                              cross(d-c, c-a), cross(d-c, d-b)])
        return {"version": DENSE_SAMPLING_VERSION,
                "direction": "prepared_pixel_centres_to_source_pixel_centres",
                "mesh_shape": list(grid.shape), "source_size": list(self.source_size),
                "prepared_size": list(self.prepared_size), "align_corners": True,
                "local_nonpositive_jacobian_cells": int(np.any(jacobians <= 0, axis=0).sum()),
                "mesh_vertices_outside_source": int(np.any((grid < -1) | (grid > 1), axis=2).sum()),
                "source_coverage_verified": False, "global_injectivity_verified": False,
                "recognition_accuracy_verified": False}
