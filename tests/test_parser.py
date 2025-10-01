import zlib
import struct
import pytest
from src.parser import (
    Block,
    Tile,
    FogMap,
    nnz,
    _tile_x_y_to_lng_lat,
    FILENAME_MASK1,
    FILENAME_MASK2,
    MAP_WIDTH,
    TILE_HEADER_LEN,
    BLOCK_BITMAP_SIZE,
)

# Helper to create a fake block data


def make_block_data(region_str="AA", ones_count=10):
    # Bitmap: 512 bytes, set exactly ones_count bits to 1
    bitmap = bytearray(BLOCK_BITMAP_SIZE)
    for i in range(ones_count):
        byte_idx = i // 8
        bit_idx = 7 - (i % 8)
        bitmap[byte_idx] |= 1 << bit_idx
    # Extra data: encode region and checksum
    region0 = ord(region_str[0]) - ord("?")
    region1 = ord(region_str[1]) - ord("?")
    extra0 = (region0 << 3) | (region1 >> 2)
    extra1 = (region1 & 0x3) << 6
    checksum = ((ones_count << 1) + 1) & 0x3FFF
    extra1 |= (checksum >> 8) & 0x3F
    extra2 = checksum & 0xFF
    extra_data = bytes([extra0, extra1, extra2])
    return bytes(bitmap) + extra_data


def test_nnz():
    data = bytes([0b10101010, 0b11110000, 0b00001111])
    assert nnz(data) == 12


def test_block_region_and_checksum():
    data = make_block_data("AB", 20)
    block = Block(1, 2, data)
    assert block.region == "AB"
    assert isinstance(block.bitmap, bytes)
    assert isinstance(block.extra_data, bytes)
    # is_visited should match the bits set
    for i in range(20):
        x = i % 64
        y = i // 64
        assert block.is_visited(x, y)


def test_tile_x_y_to_lng_lat():
    lng, lat = _tile_x_y_to_lng_lat(0, 0)
    assert -180 <= lng <= 180
    assert -90 <= lat <= 90
    lng2, lat2 = _tile_x_y_to_lng_lat(512, 512)
    assert -180 <= lng2 <= 180
    assert -90 <= lat2 <= 90


def test_tile_and_fogmap(tmp_path):
    # Create a fake Sync folder and a fake tile file
    sync_folder = tmp_path / "Sync"
    sync_folder.mkdir()
    # Fake tile id and filename
    tile_id = 1234
    tile_x = tile_id % MAP_WIDTH
    tile_y = tile_id // MAP_WIDTH
    # Encode filename
    id_digits = [int(d) for d in str(tile_id)]
    filename_mid = "".join(FILENAME_MASK1[d] for d in id_digits)
    filename_start = __import__("hashlib").md5(str(tile_id).encode()).hexdigest()[:4]
    filename_end = "".join([FILENAME_MASK2[int(i)] for i in str(tile_id)[-2:]])
    filename = filename_start + filename_mid + filename_end
    # Build header: all zeros except one block
    header = [0] * TILE_HEADER_LEN
    block_idx = 1
    block_pos = 0
    header[block_pos] = block_idx
    header_bytes = struct.pack(str(TILE_HEADER_LEN) + "H", *header)
    block_data = make_block_data("CD", 15)
    tile_bytes = header_bytes + block_data
    tile_bytes = zlib.compress(tile_bytes)
    tile_path = sync_folder / filename
    with open(tile_path, "wb") as f:
        f.write(tile_bytes)
    # Test Tile
    tile = Tile(str(sync_folder), filename)
    assert (0, 0) in tile.blocks
    assert "CD" in tile.region_set
    # Test FogMap
    fogmap = FogMap(str(tmp_path))
    assert (tile_x, tile_y) in fogmap.tile_map
    assert "CD" in fogmap.region_set
    # Test bounds
    bounds = tile.bounds()
    assert isinstance(bounds, tuple)
    assert len(bounds) == 2


if __name__ == "__main__":
    pytest.main()
