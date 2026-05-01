import struct
import numpy as np
import mmap


DRF_SYNC_BYTES = b'\xff\xff\x00\x00'
RECORD_7042 = 7042


class S7KFrame:
    __slots__ = ('ping_number', 'n_beams', 'n_samples', 'sample_rate',
                 'data', 'file_offset')

    def __init__(self, ping_number, n_beams, n_samples, sample_rate,
                 data, file_offset):
        self.ping_number = ping_number
        self.n_beams = n_beams
        self.n_samples = n_samples
        self.sample_rate = sample_rate
        self.data = data
        self.file_offset = file_offset


class S7KFile:
    def __init__(self, filepath):
        self.filepath = filepath
        self._frame_offsets = []
        self._scan_file()

    def _scan_file(self):
        with open(self.filepath, 'rb') as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            file_size = len(mm)
            pos = 0

            while pos < file_size - 64:
                idx = mm.find(DRF_SYNC_BYTES, pos)
                if idx < 0:
                    break

                drf_start = idx - 4
                if drf_start < 0:
                    pos = idx + 1
                    continue

                drf_offset = struct.unpack_from('<H', mm, drf_start + 2)[0]
                size = struct.unpack_from('<I', mm, drf_start + 8)[0]

                if not (20 <= drf_offset <= 200 and 10 < size < 500_000_000):
                    pos = idx + 1
                    continue

                record_type = struct.unpack_from('<I', mm, drf_start + 32)[0]

                if record_type == RECORD_7042:
                    self._frame_offsets.append((drf_start, size, drf_offset))

                next_pos = drf_start + size + drf_offset
                pos = max(idx + 1, next_pos)

            mm.close()

    @property
    def frame_count(self):
        return len(self._frame_offsets)

    def read_frame(self, index):
        if index < 0 or index >= len(self._frame_offsets):
            return None

        pos, size, drf_offset = self._frame_offsets[index]

        with open(self.filepath, 'rb') as f:
            f.seek(pos + drf_offset)
            raw = f.read(size)

        arr = np.frombuffer(raw, dtype='<u2')
        if len(arr) < 28:
            return None

        arr32 = np.frombuffer(raw[:48], dtype='<u4')
        ping_number = int(arr32[3])
        n_beams = int(arr[9])
        total_range = int(arr32[5])
        first_sample = int(arr32[8])
        n_samples = total_range - first_sample

        sample_rate = struct.unpack_from('<f', raw, 36)[0]

        stride = 3 + n_samples
        beam_data_start = 24

        indices = np.arange(n_beams) * stride + beam_data_start + 3
        offsets = indices[:, None] + np.arange(n_samples)
        valid = offsets[:, -1] < len(arr)
        data = np.zeros((n_beams, n_samples), dtype=np.uint16)
        if valid.any():
            n_valid = valid.sum()
            data[:n_valid] = arr[offsets[:n_valid]]

        return S7KFrame(ping_number, n_beams, n_samples, sample_rate,
                        data, pos)
