"""OpenCL Hamming nearest-neighbor search for card descriptors."""

from __future__ import annotations

import numpy as np


_KERNEL = """
__kernel void nearest(__global const uint *query, __global const uint *train,
                      const uint train_count, __global ushort *distances,
                      __global uint *indices) {
    const uint query_index = get_group_id(0);
    const uint lane = get_local_id(0);
    const uint lanes = get_local_size(0);
    uint best = 999, second = 999;
    uint best_index = 0xffffffff, second_index = 0xffffffff;
    for (uint j = lane; j < train_count; j += lanes) {
        uint distance = 0;
        for (uint word = 0; word < 8; word++)
            distance += popcount(query[query_index * 8 + word] ^ train[j * 8 + word]);
        if (distance < best) {
            second = best;
            second_index = best_index;
            best = distance;
            best_index = j;
        } else if (distance < second) {
            second = distance;
            second_index = j;
        }
    }
    const uint position = query_index * lanes + lane;
    distances[position * 2] = (ushort)best;
    distances[position * 2 + 1] = (ushort)second;
    indices[position * 2] = best_index;
    indices[position * 2 + 1] = second_index;
}
"""


def gpu_available() -> bool:
    try:
        import pyopencl as cl

        return any(
            device.type & cl.device_type.GPU
            for platform in cl.get_platforms()
            for device in platform.get_devices()
        )
    except Exception:
        return False


class OpenClHammingMatcher:
    LANES = 256

    def __init__(self, descriptors: list[np.ndarray]) -> None:
        import pyopencl as cl

        devices = [
            device
            for platform in cl.get_platforms()
            for device in platform.get_devices()
            if device.type & cl.device_type.GPU
        ]
        if not devices:
            raise RuntimeError("No OpenCL GPU is available")
        self._cl = cl
        self._context = cl.Context([devices[0]])
        self._queue = cl.CommandQueue(self._context)
        self._kernel = cl.Program(self._context, _KERNEL).build().nearest
        self._offsets = np.concatenate(([0], np.cumsum([len(item) for item in descriptors])))
        train = np.ascontiguousarray(np.vstack(descriptors)).view(np.uint32)
        self._train_count = len(train)
        self._train = cl.Buffer(
            self._context, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=train
        )

    def votes(self, descriptors: np.ndarray) -> np.ndarray:
        """Count distinctive nearest-neighbor matches for each card template."""
        cl = self._cl
        query = np.ascontiguousarray(descriptors).view(np.uint32)
        query_count = len(query)
        distances = np.empty((query_count, self.LANES, 2), dtype=np.uint16)
        indices = np.empty((query_count, self.LANES, 2), dtype=np.uint32)
        query_buffer = cl.Buffer(
            self._context, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=query
        )
        distance_buffer = cl.Buffer(self._context, cl.mem_flags.WRITE_ONLY, distances.nbytes)
        index_buffer = cl.Buffer(self._context, cl.mem_flags.WRITE_ONLY, indices.nbytes)
        self._kernel(
            self._queue,
            (query_count * self.LANES,),
            (self.LANES,),
            query_buffer,
            self._train,
            np.uint32(self._train_count),
            distance_buffer,
            index_buffer,
        )
        cl.enqueue_copy(self._queue, distances, distance_buffer)
        cl.enqueue_copy(self._queue, indices, index_buffer).wait()

        flat_distances = distances.reshape(query_count, -1)
        flat_indices = indices.reshape(query_count, -1)
        nearest_columns = np.argpartition(flat_distances, 2, axis=1)[:, :2]
        nearest_distances = np.take_along_axis(flat_distances, nearest_columns, axis=1)
        nearest_indices = np.take_along_axis(flat_indices, nearest_columns, axis=1)
        order = np.argsort(nearest_distances, axis=1)
        nearest_distances = np.take_along_axis(nearest_distances, order, axis=1)
        nearest_indices = np.take_along_axis(nearest_indices, order, axis=1)
        distinctive = nearest_distances[:, 0] < 0.75 * nearest_distances[:, 1]
        template_indices = np.searchsorted(
            self._offsets, nearest_indices[distinctive, 0], side="right"
        ) - 1
        return np.bincount(template_indices, minlength=len(self._offsets) - 1)
