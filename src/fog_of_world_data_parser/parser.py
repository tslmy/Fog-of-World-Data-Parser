"""Core parsing logic for Fog of World sync data.

This module exposes a light-weight, read‑only representation of the map
comprised of Tiles -> Blocks -> bitmaps indicating visited cells.
"""

from __future__ import annotations

import os
import math
import zlib
import struct
import hashlib
import logging
from typing import Dict, Iterable, Set, Tuple

FILENAME_MASK1: str = "olhwjsktri"
FILENAME_MASK2: str = "eizxdwknmo"
FILENAME_ENCODING: Dict[str, int] = {k: v for v, k in enumerate(FILENAME_MASK1)}

MAP_WIDTH: int = 512
TILE_WIDTH: int = 128
TILE_HEADER_LEN: int = TILE_WIDTH**2
TILE_HEADER_SIZE: int = TILE_HEADER_LEN * 2  # 2 bytes per unsigned short
BLOCK_BITMAP_SIZE: int = 512  # 64 * 64 bits == 4096 bits -> 512 bytes
BLOCK_EXTRA_DATA: int = 3
BLOCK_SIZE: int = BLOCK_BITMAP_SIZE + BLOCK_EXTRA_DATA
BITMAP_WIDTH: int = 64

# Precompute population count for every byte value 0..255
NNZ_FOR_BYTE: bytes = bytes(bin(x).count("1") for x in range(256))


def nnz(data: Iterable[int]) -> int:
    """Return the number of set bits in the given bytes-like object.

    `NNZ` is shorthand for “Number of Non-Zeros,” a common numeric/linear‑algebra abbreviation meaning “count of non‑zero entries.”
    Here, it specifically means “number of 1 bits” (a population count / bitcount) in a bytes-like bitmap.

    Parameters
    ----------
    data: Iterable[int]
        Raw bytes / bytearray / memoryview or any iterable of ints 0..255.
    """
    # Local variable lookup speed-up
    lut = NNZ_FOR_BYTE
    return sum(lut[b] for b in data)


class Block:
    """A 64x64 bitmap of visited cells plus region & checksum metadata."""

    __slots__ = ("x", "y", "bitmap", "extra_data", "region")

    def __init__(self, x: int, y: int, data: bytes) -> None:
        logger = logging.getLogger(Block.__name__)
        self.x: int = x
        self.y: int = y
        self.bitmap: bytes = data[:BLOCK_BITMAP_SIZE]
        self.extra_data: bytes = data[BLOCK_BITMAP_SIZE:BLOCK_SIZE]

        # extra_data bit layout (three bytes):
        #  XXXX XYYY  YY0Z ZZZZ  ZZZZ ZZZ1
        #  X: first region char offset by ASCII '?' (5 bits)
        #  Y: second region char offset by ASCII '?' (5 bits)
        #  Z: number of set bits in bitmap (12 bits) encoded as: checksum = (count << 1) + 1
        q = ord("?")
        region0 = (self.extra_data[0] >> 3) + q
        region1_packed = ((self.extra_data[0] & 0x07) << 2) | (
            (self.extra_data[1] & 0xC0) >> 6
        )
        region1 = region1_packed + q
        self.region: str = chr(region0) + chr(region1)
        if self.region == "@@":
            self.region = "BORDER/INTERNATIONAL"

        checksum = struct.unpack(">H", self.extra_data[1:])[0] & 0x3FFF
        expected = (nnz(self.bitmap) << 1) + 1
        if expected != checksum:
            logger.warning(
                "Block (%d,%d) checksum mismatch (expected=%d stored=%d)",
                self.x,
                self.y,
                expected,
                checksum,
            )

    def is_visited(self, x: int, y: int) -> int:
        """Return non-zero if the (x,y) cell within this block is marked visited.

        Coordinates are zero-based with 0 <= x,y < 64.
        """
        if not (0 <= x < BITMAP_WIDTH and 0 <= y < BITMAP_WIDTH):  # defensive
            raise ValueError("x and y must be in [0, 63]")
        bit_offset = 7 - (x & 0x7)
        i = x >> 3
        return self.bitmap[i + y * 8] & (1 << bit_offset)


def _tile_x_y_to_lng_lat(x: int, y: int) -> Tuple[float, float]:
    """Convert tile grid coordinates (0..512) to lon/lat using Web Mercator inverse."""
    lng = x / MAP_WIDTH * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi - 2 * math.pi * y / MAP_WIDTH)))
    return lng, lat


class Tile:
    """A tile file comprised of up to 128x128 blocks of 64x64 bitmaps."""

    # Class-level attribute type declarations (no mutable defaults assigned):
    blocks: Dict[Tuple[int, int], Block]
    region_set: Set[str]

    def __init__(self, sync_folder: str, filename: str) -> None:
        logger = logging.getLogger(Tile.__name__)
        file_path = os.path.join(sync_folder, filename)
        # Decode the numeric id from the masked digits inside the filename.
        self.id: int = 0
        for c in filename[4:-2]:
            self.id = self.id * 10 + FILENAME_ENCODING[c]
        self.x: int = self.id % MAP_WIDTH
        self.y: int = self.id // MAP_WIDTH
        logger.info("Loading tile id=%s x=%d y=%d", self.id, self.x, self.y)

        # Validate filename prefix/hash and suffix mask.
        match1 = hashlib.md5(str(self.id).encode()).hexdigest()[:4] == filename[:4]
        match2 = (
            "".join(FILENAME_MASK2[int(i)] for i in str(self.id)[-2:]) == filename[-2:]
        )
        if not (match1 and match2):
            logger.warning("Tile filename %s failed validation", filename)

        with open(file_path, "rb") as f:
            raw = f.read()
        try:
            data = zlib.decompress(raw)
        except zlib.error as e:
            raise ValueError(f"Failed to decompress tile {filename}") from e

        # Header: TILE_HEADER_LEN unsigned shorts mapping to block indices
        header_fmt = f"{TILE_HEADER_LEN}H"
        header = struct.unpack(header_fmt, data[:TILE_HEADER_SIZE])
        self.blocks: Dict[Tuple[int, int], Block] = {}
        self.region_set: Set[str] = set()
        # Iterate only over non-zero block indices
        for i, block_idx in enumerate(header):
            if block_idx == 0:
                continue
            block_x = i % TILE_WIDTH
            block_y = i // TILE_WIDTH
            start_offset = TILE_HEADER_SIZE + (block_idx - 1) * BLOCK_SIZE
            end_offset = start_offset + BLOCK_SIZE
            block_data = data[start_offset:end_offset]
            block = Block(block_x, block_y, block_data)
            self.region_set.add(block.region)
            self.blocks[(block_x, block_y)] = block

    def bounds(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """Return (south_west, north_east) geographic bounds of this tile."""
        lng1, lat1 = _tile_x_y_to_lng_lat(self.x, self.y)
        lng2, lat2 = _tile_x_y_to_lng_lat(self.x + 1, self.y + 1)
        return ((min(lat1, lat2), min(lng1, lng2)), (max(lat1, lat2), max(lng1, lng2)))


class FogMap:
    """Represents the entire explored map.

    The whole map is composed of 512x512 tiles.
    Each tile is 128x128 blocks of 64x64 bitmaps.

    Directory layout expected:
        <root>/Sync/<tile files>
    """

    def __init__(self, path: str) -> None:
        logger = logging.getLogger(FogMap.__name__)
        self.path: str = os.path.join(path, "")
        sync_folder = os.path.join(self.path, "Sync")
        if not os.path.isdir(sync_folder):
            raise FileNotFoundError(f"Sync directory not found under: {path}")
        # Instance attributes
        self.tile_map: Dict[Tuple[int, int], Tile] = {}
        self.region_set: Set[str] = set()
        for filename in os.listdir(sync_folder):
            try:
                tile = Tile(sync_folder, filename)
            except Exception:  # broad but we want to continue best-effort
                logger.exception("Failed to load tile file %s", filename)
                continue
            self.region_set.update(tile.region_set)
            self.tile_map[(tile.x, tile.y)] = tile
        logger.info("Traversed regions: %s", self.region_set)
