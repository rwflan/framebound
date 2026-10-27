"""Minimal PNG read/write using only the standard library.

Supports 8-bit non-interlaced PNG (colour types 0, 2, 3, 4, 6).
Images are (width, height, RGBA bytes). No third-party dependency is
required anywhere in the core checker, so it runs in any Python 3.11+.
"""
import struct
import zlib


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_png(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a PNG: {path}")
    pos, idat, plte, trns = 8, b"", None, None
    width = height = bitdepth = colour = None
    while pos < len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bitdepth, colour = struct.unpack(">IIBB", chunk[:10])
            if bitdepth != 8:
                raise ValueError("Only 8-bit PNG is supported")
        elif ctype == b"PLTE":
            plte = chunk
        elif ctype == b"tRNS":
            trns = chunk
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    raw = zlib.decompress(idat)
    stride = width * channels
    out = bytearray(width * height * 4)
    prev = bytearray(stride)
    p = 0
    for y in range(height):
        filt = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        for i in range(stride):
            a = line[i - channels] if i >= channels else 0
            b = prev[i]
            c = prev[i - channels] if i >= channels else 0
            if filt == 1:
                line[i] = (line[i] + a) & 255
            elif filt == 2:
                line[i] = (line[i] + b) & 255
            elif filt == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif filt == 4:
                line[i] = (line[i] + _paeth(a, b, c)) & 255
        prev = line
        for x in range(width):
            s, d = x * channels, (y * width + x) * 4
            if colour == 6:
                out[d:d + 4] = line[s:s + 4]
            elif colour == 2:
                out[d:d + 3] = line[s:s + 3]; out[d + 3] = 255
            elif colour == 0:
                out[d] = out[d + 1] = out[d + 2] = line[s]; out[d + 3] = 255
            elif colour == 4:
                out[d] = out[d + 1] = out[d + 2] = line[s]; out[d + 3] = line[s + 1]
            elif colour == 3:
                idx = line[s] * 3
                out[d:d + 3] = plte[idx:idx + 3]
                out[d + 3] = trns[line[s]] if trns and line[s] < len(trns) else 255
    return width, height, bytes(out)


def write_png(path, width, height, rgba):
    def chunk(ctype, payload):
        body = ctype + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


def sha256_file(path):
    import hashlib
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def pixel_sha256(width, height, rgba):
    import hashlib
    return hashlib.sha256(rgba).hexdigest()
