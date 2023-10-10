def bytepack(data: list[int]) -> bytearray:
    tmp: list = data
    # checksum
    checksum: int = sum(data) % 256
    tmp.append(checksum)
    # hex
    for e in tmp:
        e = e & 0xFF
    return bytearray(tmp)


def gen_packet_content(type: int, data: list[int]) -> list[int]:
    # gen tmp
    tmp: list[int] = []
    for e in data:
        if e > 255:
            tmp.append(e // 256)
            tmp.append(e % 256)
        else:
            tmp.append(e)
    # insert length
    tmp.insert(0, len(tmp))
    # insert type
    tmp.insert(0, type)
    return tmp
