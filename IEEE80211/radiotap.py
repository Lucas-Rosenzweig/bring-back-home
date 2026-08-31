"""Small Radiotap helpers used by the monitor socket."""


def _frequency_to_channel(frequency: int) -> int | None:
    if frequency == 2484:
        return 14
    if 2412 <= frequency <= 2472 and (frequency - 2407) % 5 == 0:
        return (frequency - 2407) // 5
    if 4910 <= frequency <= 4980 and (frequency - 4000) % 5 == 0:
        return (frequency - 4000) // 5
    if 5000 <= frequency <= 5895 and (frequency - 5000) % 5 == 0:
        return (frequency - 5000) // 5
    if frequency == 5935:
        return 2
    if 5955 <= frequency <= 7115 and (frequency - 5950) % 5 == 0:
        return (frequency - 5950) // 5
    return None


def extract_frame(packet: bytes) -> tuple[bytes, int | None] | None:
    """Return the 802.11 frame and capture channel from a Radiotap packet.

    Only the initial fields needed here are decoded.  The extended presence
    bitmap is still walked so field alignment remains correct.
    """
    if len(packet) < 8 or packet[0] != 0:
        return None

    header_length = int.from_bytes(packet[2:4], "little")
    if header_length < 8 or header_length > len(packet):
        return None

    presence_offset = 4
    first_presence_word: int | None = None
    while True:
        if presence_offset + 4 > header_length:
            return None
        presence_word = int.from_bytes(
            packet[presence_offset : presence_offset + 4],
            "little",
        )
        if first_presence_word is None:
            first_presence_word = presence_word
        presence_offset += 4
        if not presence_word & (1 << 31):
            break

    assert first_presence_word is not None
    offset = presence_offset
    flags: int | None = None
    channel: int | None = None
    field_layout = (
        (8, 8),  # TSFT
        (1, 1),  # Flags
        (1, 1),  # Rate
        (2, 4),  # Channel: frequency and flags
    )

    for index, (alignment, size) in enumerate(field_layout):
        if not first_presence_word & (1 << index):
            continue
        offset = (offset + alignment - 1) & -alignment
        if offset + size > header_length:
            return None
        if index == 1:
            flags = packet[offset]
        elif index == 3:
            frequency = int.from_bytes(packet[offset : offset + 2], "little")
            channel = _frequency_to_channel(frequency)
        offset += size

    frame = packet[header_length:]
    if flags is not None and flags & 0x10:  # IEEE 802.11 FCS included
        if len(frame) < 4:
            return None
        frame = frame[:-4]

    if not frame:
        return None
    return frame, channel
