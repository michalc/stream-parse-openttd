import lzma
import struct


def stream_parse_openttd(chunks, chunk_size=65536):
    CH_RIFF = 0
    CH_ARRAY = 1 # Deprecated
    CH_SPARSE_ARRAY = 2 # Deprecated
    CH_TABLE = 3
    CH_SPARSE_TABLE = 4

    def uint24(b):
        return (b[0] << 16) + (b[1] << 8) + b[2]

    def byte_readers(iterable):
        chunk = b''
        offset = 0
        it = iter(iterable)

        def _yield_num(num):
            nonlocal chunk, offset

            while num:
                if offset == len(chunk):
                    chunk = next(it)
                    offset = 0
                to_yield = min(num, len(chunk) - offset, chunk_size)
                num -= to_yield
                offset += to_yield
                yield chunk[offset - to_yield:offset]

        def _yield_remaining():
            yield from _yield_num(float('inf'))

        def _get_num(num):
            return b''.join(_yield_num(num))

        return _yield_remaining, _yield_num, _get_num

    def decompress(compressed_chunks):
        decompressor = lzma.LZMADecompressor()
        for compressed_chunk in compressed_chunks:
            chunk = decompressor.decompress(compressed_chunk, max_length=chunk_size)
            if chunk:
                yield chunk

            while not decompressor.eof:
                chunk = decompressor.decompress(b'', max_length=chunk_size)
                if not chunk:
                    break
                yield chunk

    def has_bit(i, k):
        return i & (1 << k)

    def read_gamma(get_num):
        i = get_num(1)[0]
        if has_bit(i, 7):
            i &= ~0x80
            if has_bit(i, 6):
                i &= ~0x40;
                if has_bit(i, 5):
                    i &= ~0x20;
                    if has_bit(i, 4):
                        i &= ~0x10;
                        if has_bit(i, 3):
                            raise Exception('Bad gamma')
                        i = get_num(1)[0]
                    i = (i << 8) | get_num(1)[0]
                i = (i << 8) | get_num(1)[0]
            i = (i << 8) | get_num(1)[0]
        return i

    SIMPLE_TYPES = {
        1: struct.Struct('>b'),
        2: struct.Struct('>B'),
        3: struct.Struct('>h'),
        4: struct.Struct('>H'),
        5: struct.Struct('>i'),
        6: struct.Struct('>I'),
        7: struct.Struct('>q'),
        8: struct.Struct('>Q'),
        9: struct.Struct('>H'),
    }

    def parse_simple(get_num, struct_obj, is_list):
        num_repeats = \
            read_gamma(get_num) if is_list else \
            1
        return [
            struct_obj.unpack(get_num(struct_obj.size))[0]
            for _ in range(0, num_repeats)
        ]

    def parse_str(get_num, repeats):
        num_repeats = read_gamma(get_num)
        return [
            get_num(read_gamma(get_num)).decode('utf-8')
            for _ in range(0, num_repeats)
        ]

    yield_remaining, _, get_num = byte_readers(chunks)

    # Initial uncompressed data
    compression_format = get_num(4)
    if compression_format != b'OTTX':
        raise Exception(f"Unsupported compression format {compression_format}")
    version = get_num(2)
    _ = get_num(2)

    # Decompressed data
    decompressed = decompress(yield_remaining())
    yield_remaining, yield_num, get_num = byte_readers(decompressed)

    while True:
        chunk_id = get_num(4)

        if chunk_id == b'\0\0\0\0':
            print("Done")
            return

        chunk_raw_type = get_num(1)[0]
        chunk_type = chunk_raw_type & 0xf

        yield chunk_id, chunk_type

        if chunk_type == CH_RIFF:
            length = uint24(get_num(3))
            length |= ((chunk_raw_type >> 4) << 24)
            for _ in yield_num(length):
                pass

        elif chunk_type in (CH_TABLE, CH_SPARSE_TABLE):
            num_headers_plus_one = read_gamma(get_num)
            if num_headers_plus_one == 0:
                raise Exception("Bad header")

            def _headers():
                # Recursive, but don't expect many levels

                def _this_level():
                    while True:
                        record_type_raw = get_num(1)[0]
                        record_type = record_type_raw & 0xf
                        with_repeat = bool(record_type_raw & 0x10)
                        if record_type == 0:
                            break
                        key_length = read_gamma(get_num)
                        key = get_num(key_length)
                        yield key, record_type, with_repeat

                for key, record_type, with_repeat in tuple(_this_level()):
                    sub_headers = \
                        _headers() if record_type == 11 else \
                        ()
                    yield key, record_type, with_repeat, tuple(sub_headers)

            def _records(headers):
                # Recursive, but don't expect many levels

                for key, record_type, with_repeat, sub_headers in headers:
                    num_repeats = \
                        read_gamma(get_num) if with_repeat else \
                        1
                    if record_type in SIMPLE_TYPES:
                        for i in range(0, num_repeats):
                            struct_obj = SIMPLE_TYPES[record_type]
                            value = struct_obj.unpack(get_num(struct_obj.size))[0]
                    elif record_type == 10:
                        for i in range(0, num_repeats):
                            str_len = read_gamma(get_num)
                            value = get_num(str_len)
                    elif record_type == 11:
                        for _ in range(0, num_repeats):
                            _records(sub_headers)

            headers = tuple(_headers())

            count = 0
            while True:
                size = read_gamma(get_num)
                if size == 0:
                    break

                if chunk_id in (b'AIPL', b'GSDT'):
                    get_num(size)
                    get_num(1)
                    continue

                if chunk_type == CH_SPARSE_TABLE:
                    index = read_gamma(get_num)

                _records(headers)
                count += 1

        else:
            raise Exception('Unsupported chunk')
