import struct
import numpy as np
import mmap


DRF_SYNC_BYTES = b'\xff\xff\x00\x00'

_record_parsers = {}


def register_record(record_type):
    def decorator(cls):
        cls.record_type = record_type
        _record_parsers[record_type] = cls
        return cls
    return decorator


class S7KRecord:
    __slots__ = ('file_offset',)
    record_type = None

    def __init__(self, file_offset):
        self.file_offset = file_offset

    @classmethod
    def parse(cls, raw, file_offset):
        raise NotImplementedError


@register_record(7000)
class SonarSettingsRecord(S7KRecord):
    __slots__ = ('swath_angle',)

    def __init__(self, file_offset, swath_angle):
        super().__init__(file_offset)
        self.swath_angle = swath_angle

    @classmethod
    def parse(cls, raw, file_offset):
        if len(raw) < 28:
            return None
        swath_angle = struct.unpack_from('<f', raw, 24)[0]
        return cls(file_offset, swath_angle)


@register_record(7042)
class WaterColumnRecord(S7KRecord):
    __slots__ = ('ping_number', 'n_beams', 'n_samples', 'sample_rate', 'data')

    def __init__(self, file_offset, ping_number, n_beams, n_samples,
                 sample_rate, data):
        super().__init__(file_offset)
        self.ping_number = ping_number
        self.n_beams = n_beams
        self.n_samples = n_samples
        self.sample_rate = sample_rate
        self.data = data

    @classmethod
    def parse(cls, raw, file_offset):
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

        return cls(file_offset, ping_number, n_beams, n_samples,
                   sample_rate, data)


class S7KFile:
    def __init__(self, filepath, record_types=None):
        self.filepath = filepath
        self._record_offsets = {}
        self._record_types = (
            set(record_types) if record_types else set(_record_parsers.keys())
        )
        self.swath_angle = None
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

                if record_type in self._record_types:
                    self._record_offsets.setdefault(record_type, []).append(
                        (drf_start, size, drf_offset))

                next_pos = drf_start + size + drf_offset
                pos = max(idx + 1, next_pos)

            mm.close()

        self._extract_metadata()

    def _extract_metadata(self):
        rec = self.read_record(7000, 0)
        if rec:
            self.swath_angle = rec.swath_angle

    @property
    def frame_count(self):
        return self.record_count(7042)

    def record_count(self, record_type):
        return len(self._record_offsets.get(record_type, []))

    def read_record(self, record_type, index):
        offsets = self._record_offsets.get(record_type, [])
        if index < 0 or index >= len(offsets):
            return None
        parser = _record_parsers.get(record_type)
        if not parser:
            return None
        pos, size, drf_offset = offsets[index]
        with open(self.filepath, 'rb') as f:
            f.seek(pos + drf_offset)
            raw = f.read(size)
        return parser.parse(raw, pos)

    def read_all_records(self, record_type):
        offsets = self._record_offsets.get(record_type, [])
        parser = _record_parsers.get(record_type)
        if not parser or not offsets:
            return []
        records = []
        with open(self.filepath, 'rb') as f:
            for pos, size, drf_offset in offsets:
                f.seek(pos + drf_offset)
                raw = f.read(size)
                rec = parser.parse(raw, pos)
                if rec:
                    records.append(rec)
        return records

    def read_frame(self, index):
        return self.read_record(7042, index)
