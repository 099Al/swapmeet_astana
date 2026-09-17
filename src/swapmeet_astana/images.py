from __future__ import annotations

import io

from PIL import Image


def dhash(image_bytes: bytes, hash_size: int = 8) -> str:
    image = Image.open(io.BytesIO(image_bytes)).convert("L").resize((hash_size + 1, hash_size))
    pixels = list(image.getdata())
    bits: list[str] = []
    for row in range(hash_size):
        offset = row * (hash_size + 1)
        for col in range(hash_size):
            bits.append("1" if pixels[offset + col] > pixels[offset + col + 1] else "0")
    return f"{int(''.join(bits), 2):0{hash_size * hash_size // 4}x}"


def hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()
