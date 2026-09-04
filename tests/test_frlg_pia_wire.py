from __future__ import annotations

import time
import unittest

from pokemon_trade.games.frlg.gba.frame import ChildSlotFrame, ControlFrame, FrameType, HostSlotFrame
from pokemon_trade.games.frlg.gba.rfu import RfuCommand, RfuSlot, uni_slot
from pokemon_trade.games.frlg.pia.crypto import decrypt_frlg_v16, encrypt_frlg_v16
from pokemon_trade.games.frlg.pia.packet import PiaMessage as PacketMessage
from pokemon_trade.games.frlg.pia.packet import PiaPacketV16, decode_messages_v16, encode_messages_v16
from pokemon_trade.games.frlg.pia.peer import PiaPeer
from pokemon_trade.games.frlg.pia.reliable import RELIABLE_APP_DATA, RELIABLE_MESSAGE_END, RELIABLE_MESSAGE_START, ReliableWireFrame
from pokemon_trade.games.frlg.pia.session import PiaProtocol, PiaSession
from pokemon_trade.games.frlg.pia.wire import (
    RELIABLE_CONTROL_ACK_SECONDS,
    RELIABLE_MAX_ACK_INFLIGHT,
    RELIABLE_MAX_INFLIGHT,
    RELIABLE_SEQUENCE_START,
    FrlgPiaWire,
    _next_wire_sequence,
)


class FrlgPiaWireTest(unittest.TestCase):
    def test_decrypts_reliable_application_into_a_host_gba_frame(self) -> None:
        ssid, key = bytes(range(16)), bytes(range(16))
        peer = PiaPeer(PiaSession(local_constant_id=b"\x01" * 6, local_ip="169.254.1.2", player_name="EMU", random_nonce=bytes(4), app_version=88), ssid=ssid, game_key=key, local_ip="169.254.1.2")
        wire = FrlgPiaWire(peer)
        host_frame = b"WT\x08\0\x09\0\0\0\0\0\0\0"
        reliable = ReliableWireFrame(RELIABLE_APP_DATA | RELIABLE_MESSAGE_START | RELIABLE_MESSAGE_END | 0x08, 1, 1, host_frame)
        incoming = encrypt_frlg_v16(
            ssid=ssid, game_key=key, source_ip="169.254.1.1", destination_variable_id=0x1111, source_variable_id=0x2222,
            packet_id=1, nonce=bytes(8), application=encode_messages_v16((PacketMessage(0, PiaProtocol.RELIABLE, 0, 0, reliable.encode()),)), footer=b"\x11\x11",
        ).encode()

        self.assertEqual(wire.receive_datagram(incoming, "169.254.1.1"), (HostSlotFrame(9, b""),))

    def test_forwards_initialized_host_accept_frame(self) -> None:
        ssid, key = bytes(range(16)), bytes(range(16))
        peer = PiaPeer(PiaSession(local_constant_id=b"\x01" * 6, local_ip="169.254.1.2", player_name="EMU", random_nonce=bytes(4), app_version=88), ssid=ssid, game_key=key, local_ip="169.254.1.2")
        wire = FrlgPiaWire(peer)
        accept = b"WA\x02\0\x12\x34"
        reliable = ReliableWireFrame(RELIABLE_APP_DATA | RELIABLE_MESSAGE_START | RELIABLE_MESSAGE_END | 0x08, 1, 1, accept)
        incoming = encrypt_frlg_v16(
            ssid=ssid, game_key=key, source_ip="169.254.1.1", destination_variable_id=0x1111, source_variable_id=0x2222,
            packet_id=1, nonce=bytes(8), application=encode_messages_v16((PacketMessage(0, PiaProtocol.RELIABLE, 0, 0, reliable.encode()),)), footer=b"\x11\x11",
        ).encode()

        self.assertEqual(wire.receive_datagram(incoming, "169.254.1.1"), (ControlFrame(FrameType.ACCEPT, b"\x12\x34"),))

    def test_poll_overtaking_initialized_accept_is_not_learned_or_acked(self) -> None:
        ssid, key = bytes(range(16)), bytes(range(16))
        session = PiaSession(local_constant_id=b"\x01" * 6, local_ip="169.254.1.2", player_name="EMU", random_nonce=bytes(4), app_version=88)
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        wire = FrlgPiaWire(PiaPeer(session, ssid=ssid, game_key=key, local_ip="169.254.1.2"))

        def datagram(frame: ReliableWireFrame, packet_id: int) -> bytes:
            return encrypt_frlg_v16(
                ssid=ssid, game_key=key, source_ip="169.254.1.1",
                destination_variable_id=0x1111, source_variable_id=0x2222,
                packet_id=packet_id, nonce=packet_id.to_bytes(8, "big"),
                application=encode_messages_v16((PacketMessage(0, PiaProtocol.RELIABLE, 0, 0, frame.encode()),)),
                footer=b"\x11\x11",
            ).encode()

        poll = ReliableWireFrame(
            RELIABLE_APP_DATA | RELIABLE_MESSAGE_START | RELIABLE_MESSAGE_END,
            2, 1, b"WT\x08\0\x09\0\0\0\0\0\0\0",
        )
        accept = ReliableWireFrame(
            RELIABLE_APP_DATA | RELIABLE_MESSAGE_START | RELIABLE_MESSAGE_END | 0x08,
            1, 1, b"WA\x02\0\x12\x34",
        )

        self.assertEqual(wire.receive_datagram(datagram(poll, 1), "169.254.1.1"), ())
        self.assertFalse(wire._control_ack_owed)
        self.assertEqual(
            wire.receive_datagram(datagram(accept, 2), "169.254.1.1"),
            (ControlFrame(FrameType.ACCEPT, b"\x12\x34"),),
        )
        self.assertEqual(
            wire.receive_datagram(datagram(poll, 3), "169.254.1.1"),
            (HostSlotFrame(9, b""),),
        )

    def test_forwards_each_batched_host_frame(self) -> None:
        ssid, key = bytes(range(16)), bytes(range(16))
        peer = PiaPeer(PiaSession(local_constant_id=b"\x01" * 6, local_ip="169.254.1.2", player_name="EMU", random_nonce=bytes(4), app_version=88), ssid=ssid, game_key=key, local_ip="169.254.1.2")
        wire = FrlgPiaWire(peer)
        group = ReliableWireFrame(RELIABLE_APP_DATA | RELIABLE_MESSAGE_START | RELIABLE_MESSAGE_END | 0x08, 1, 1, b"WG\0\0")
        slot = ReliableWireFrame(RELIABLE_APP_DATA | RELIABLE_MESSAGE_START | RELIABLE_MESSAGE_END, 2, 1, b"WT\x08\0\x09\0\0\0\0\0\0\0")
        incoming = encrypt_frlg_v16(
            ssid=ssid, game_key=key, source_ip="169.254.1.1", destination_variable_id=0x1111, source_variable_id=0x2222,
            packet_id=1, nonce=bytes(8), application=encode_messages_v16((
                PacketMessage(0, PiaProtocol.RELIABLE, 0, 0, group.encode()),
                PacketMessage(0, PiaProtocol.RELIABLE, 0, 0, slot.encode()),
            )), footer=b"\x11\x11",
        ).encode()

        self.assertEqual(
            wire.receive_datagram(incoming, "169.254.1.1"),
            (ControlFrame(FrameType.GROUP, b""), HostSlotFrame(9, b"")),
        )

    def test_opens_reliable_with_metadata_and_retransmits_unacknowledged_frames(self) -> None:
        session = PiaSession(
            local_constant_id=b"\x01" * 6,
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        peer = PiaPeer(session, ssid=bytes(range(16)), game_key=bytes(range(16)), local_ip="169.254.1.2")
        wire = FrlgPiaWire(peer)

        wire.queue_frame(b"WC\x02\0\x12\x34", initialized=True)
        self.assertEqual(len(wire.drain_datagrams()), 1)
        wire.poll_retransmissions(now=10**12)
        self.assertEqual(len(wire.drain_datagrams()), 1)

    def test_retransmission_timeout_tracks_clean_rtt_samples(self) -> None:
        now = [10.0]
        session = PiaSession(
            local_constant_id=b"\x01" * 6,
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        wire = FrlgPiaWire(
            PiaPeer(
                session,
                ssid=bytes(range(16)),
                game_key=bytes(range(16)),
                local_ip="169.254.1.2",
            ),
            clock=lambda: now[0],
        )
        wire.queue_frame(b"WG\0\0")
        wire.drain_datagrams()
        now[0] = 10.1
        wire._apply_acknowledgement(
            b"\0\x01" + (RELIABLE_SEQUENCE_START + 1).to_bytes(2, "big") + bytes(16)
        )

        self.assertAlmostEqual(wire.retransmission_timeout, 0.173)

        wire.queue_frame(b"WG\0\0")
        wire.drain_datagrams()
        now[0] += wire.retransmission_timeout - 0.001
        wire.poll_retransmissions()
        self.assertEqual(wire.drain_datagrams(), ())
        now[0] += 0.002
        wire.poll_retransmissions()
        self.assertEqual(len(wire.drain_datagrams()), 1)

    def test_acknowledgements_use_control_sequence_without_spending_data_ids(self) -> None:
        session = PiaSession(
            local_constant_id=b"\x01" * 6,
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        peer = PiaPeer(session, ssid=bytes(range(16)), game_key=bytes(range(16)), local_ip="169.254.1.2")
        wire = FrlgPiaWire(peer)

        wire._queue_ack()
        packet = PiaPacketV16.parse(wire.drain_datagrams()[0])
        application, _ = decrypt_frlg_v16(packet, bytes(range(16)), bytes(range(16)), "169.254.1.2")
        message = decode_messages_v16(application)[0]
        reliable = ReliableWireFrame.parse(message.payload)

        self.assertEqual(message.flags, 0x40)
        self.assertEqual(reliable.sequence, RELIABLE_SEQUENCE_START)
        self.assertEqual(wire._next_sequence, RELIABLE_SEQUENCE_START)

    def test_bulk_ack_follows_queued_emulator_data(self) -> None:
        session = PiaSession(
            local_constant_id=b"\x01" * 6,
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        wire = FrlgPiaWire(PiaPeer(session, ssid=bytes(range(16)), game_key=bytes(range(16)), local_ip="169.254.1.2"))

        wire.queue_frame(b"WG\0\0")
        wire._queue_ack()
        datagrams = wire.drain_datagrams()
        self.assertEqual(len(datagrams), 1)
        packet = PiaPacketV16.parse(datagrams[0])
        application, _ = decrypt_frlg_v16(
            packet, bytes(range(16)), bytes(range(16)), "169.254.1.2"
        )
        messages = decode_messages_v16(application)
        decoded = tuple(ReliableWireFrame.parse(message.payload) for message in messages)
        self.assertEqual(len(decoded), 2)
        self.assertEqual([message.flags for message in messages], [0, 0x40])
        self.assertTrue(decoded[0].flags & RELIABLE_APP_DATA)
        self.assertFalse(decoded[1].flags & RELIABLE_APP_DATA)

    def test_coalesces_control_acknowledgements_until_the_delayed_ack_interval(self) -> None:
        session = PiaSession(
            local_constant_id=b"\x01" * 6,
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        wire = FrlgPiaWire(PiaPeer(session, ssid=bytes(range(16)), game_key=bytes(range(16)), local_ip="169.254.1.2"))
        wire._last_control_ack_at = time.monotonic()

        wire._queue_ack()
        wire._queue_ack()
        self.assertEqual(wire.drain_datagrams(), ())
        wire._last_control_ack_at -= RELIABLE_CONTROL_ACK_SECONDS
        self.assertEqual(len(wire.drain_datagrams()), 1)

    def test_discards_only_unsent_idle_slots_before_a_priority_block(self) -> None:
        session = PiaSession(
            local_constant_id=b"\x01" * 6,
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        wire = FrlgPiaWire(PiaPeer(session, ssid=bytes(range(16)), game_key=bytes(range(16)), local_ip="169.254.1.2"))
        idle = ChildSlotFrame(1, uni_slot(RfuSlot.idle())).encode()
        for _ in range(RELIABLE_MAX_INFLIGHT + 3):
            wire.queue_frame(idle)

        wire.discard_pending_child_idle_slots()

        self.assertEqual(len(wire._unacknowledged), RELIABLE_MAX_INFLIGHT)
        self.assertEqual(len(wire._pending_data), 0)

    def test_card_phase_discards_unsent_standby_but_preserves_block_data(self) -> None:
        session = PiaSession(
            local_constant_id=b"\x01" * 6,
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        wire = FrlgPiaWire(PiaPeer(session, ssid=bytes(range(16)), game_key=bytes(range(16)), local_ip="169.254.1.2"))
        idle = ChildSlotFrame(1, uni_slot(RfuSlot.idle())).encode()
        standby = ChildSlotFrame(
            2, uni_slot(RfuSlot((RfuCommand.READY_EXIT_STANDBY, 0, 0, 0, 0, 0, 0)))
        ).encode()
        card_init = ChildSlotFrame(3, uni_slot(RfuSlot.block_init(9))).encode()
        wire._pending_data.extend(((idle, False), (standby, False), (card_init, False)))

        wire.discard_pending_child_idle_slots(discard_standby=True)

        self.assertEqual(tuple(frame for frame, _ in wire._pending_data), ())
        self.assertEqual(
            tuple(frame.payload for frame, _, _ in wire._unacknowledged.values()),
            (card_init,),
        )

    def test_phase_compaction_preserves_already_sequenced_frames(self) -> None:
        session = PiaSession(
            local_constant_id=b"\x01" * 6,
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        wire = FrlgPiaWire(PiaPeer(session, ssid=bytes(range(16)), game_key=bytes(range(16)), local_ip="169.254.1.2"))
        standby = ChildSlotFrame(
            2, uni_slot(RfuSlot((RfuCommand.READY_EXIT_STANDBY, 0, 0, 0, 0, 0, 0)))
        ).encode()
        card_init = ChildSlotFrame(3, uni_slot(RfuSlot.block_init(9))).encode()
        wire.queue_frame(standby)
        wire.queue_frame(card_init)

        wire.discard_pending_child_idle_slots(discard_standby=True)

        self.assertEqual(
            tuple(frame.payload for frame, _, _ in wire._unacknowledged.values()),
            (standby, card_init),
        )
        self.assertEqual(len(wire._pending_pia_reliable), 2)

    def test_holds_excess_frames_until_the_host_acknowledges_the_window(self) -> None:
        session = PiaSession(
            local_constant_id=b"\x01" * 6,
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        wire = FrlgPiaWire(PiaPeer(session, ssid=bytes(range(16)), game_key=bytes(range(16)), local_ip="169.254.1.2"))

        for _ in range(RELIABLE_MAX_INFLIGHT + 1):
            wire.queue_frame(b"WG\0\0")
        datagrams = wire.drain_datagrams()
        self.assertEqual(len(datagrams), 1)
        packet = PiaPacketV16.parse(datagrams[0])
        application, _ = decrypt_frlg_v16(packet, bytes(range(16)), bytes(range(16)), "169.254.1.2")
        self.assertEqual(len(decode_messages_v16(application)), RELIABLE_MAX_INFLIGHT)
        self.assertEqual(len(wire._pending_data), 1)

        next_expected = (RELIABLE_SEQUENCE_START + RELIABLE_MAX_INFLIGHT).to_bytes(2, "big")
        wire._apply_acknowledgement(b"\0\x01" + next_expected + bytes(16))
        wire.poll_retransmissions()
        self.assertEqual(len(wire.drain_datagrams()), 1)

    def test_timestamp_acks_cannot_starve_an_rfu_frame(self) -> None:
        session = PiaSession(
            local_constant_id=b"\x01" * 6,
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        wire = FrlgPiaWire(PiaPeer(session, ssid=bytes(range(16)), game_key=bytes(range(16)), local_ip="169.254.1.2"))

        for _ in range(RELIABLE_MAX_ACK_INFLIGHT + 1):
            wire.queue_frame(b"WK\x0c\0" + bytes(12))
        wire.queue_frame(b"WC\x02\0\x12\x34")

        self.assertEqual(len(wire._pending_ack_frames), 1)
        self.assertEqual(len(wire._pending_data), 0)
        self.assertEqual(sum(is_ack for _, _, is_ack in wire._unacknowledged.values()), RELIABLE_MAX_ACK_INFLIGHT)
        datagrams = wire.drain_datagrams()
        self.assertEqual(len(datagrams), 1)
        packet = PiaPacketV16.parse(datagrams[0])
        application, _ = decrypt_frlg_v16(
            packet, bytes(range(16)), bytes(range(16)), "169.254.1.2"
        )
        self.assertEqual(
            len(decode_messages_v16(application)),
            RELIABLE_MAX_ACK_INFLIGHT + 1,
        )

    def test_pending_timestamp_ack_claims_the_next_window_space(self) -> None:
        session = PiaSession(
            local_constant_id=b"\x01" * 6,
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        wire = FrlgPiaWire(PiaPeer(session, ssid=bytes(range(16)), game_key=bytes(range(16)), local_ip="169.254.1.2"))

        for _ in range(RELIABLE_MAX_INFLIGHT + 1):
            wire.queue_frame(b"WG\0\0")
        wire.queue_frame(b"WK\x0c\0" + bytes(12))
        wire.drain_datagrams()

        wire._apply_acknowledgement(b"\0\x01" + (RELIABLE_SEQUENCE_START + 1).to_bytes(2, "big") + bytes(16))
        wire.poll_retransmissions()
        newest = wire._unacknowledged[RELIABLE_SEQUENCE_START + RELIABLE_MAX_INFLIGHT][0]
        self.assertEqual(newest.payload[:2], b"WK")
        self.assertEqual(len(wire._pending_data), 1)

    def test_timestamp_ack_discovered_after_bulk_ack_preempts_idle_backlog(self) -> None:
        session = PiaSession(
            local_constant_id=b"\x01" * 6,
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        wire = FrlgPiaWire(PiaPeer(session, ssid=bytes(range(16)), game_key=bytes(range(16)), local_ip="169.254.1.2"))
        idle = ChildSlotFrame(1, uni_slot(RfuSlot.idle())).encode()
        for _ in range(RELIABLE_MAX_INFLIGHT * 2):
            wire.queue_frame(idle)
        wire.drain_datagrams()

        next_expected = (RELIABLE_SEQUENCE_START + RELIABLE_MAX_INFLIGHT).to_bytes(2, "big")
        wire._apply_acknowledgement(b"\0\x01" + next_expected + bytes(16))
        wire.queue_frame(b"WK\x0c\0" + bytes(12))

        newest = wire._unacknowledged[RELIABLE_SEQUENCE_START + RELIABLE_MAX_INFLIGHT][0]
        self.assertEqual(newest.payload[:2], b"WK")
        self.assertEqual(len(wire._pending_data), 1)

    def test_wire_sequence_wraps_to_zero(self) -> None:
        self.assertEqual(_next_wire_sequence(0xFFFF), 0)

    def test_first_host_data_sequence_is_learned_from_an_active_lobby(self) -> None:
        session = PiaSession(
            local_constant_id=b"\x01" * 6,
            local_ip="169.254.1.2",
            player_name="EMU",
            random_nonce=bytes(4),
            app_version=88,
        )
        session.local_variable_id, session.host_variable_id = 0x1111, 0x2222
        wire = FrlgPiaWire(PiaPeer(session, ssid=bytes(range(16)), game_key=bytes(range(16)), local_ip="169.254.1.2"))

        self.assertTrue(wire._note_received(8))
        self.assertEqual(wire._receive_next, 9)
