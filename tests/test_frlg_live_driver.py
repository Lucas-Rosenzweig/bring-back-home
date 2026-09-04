from __future__ import annotations

import unittest

import trio

from pokemon_trade.errors import ProtocolStateError
from pokemon_trade.games.frlg.driver import PIA_JOIN_RETRY_SECONDS, FrlgLiveWireConfig, FrlgPiaRfuDriver
from pokemon_trade.games.frlg.gba.frame import ControlFrame, FrameType
from pokemon_trade.games.frlg.gba.link import RfuFollowerLink
from pokemon_trade.games.frlg.gba.ni import NiState
from pokemon_trade.games.frlg.gba.rfu import RfuSlot, uni_slot
from pokemon_trade.games.frlg.pia.crypto import decrypt_frlg_v16, encrypt_frlg_v16
from pokemon_trade.games.frlg.pia.packet import PiaMessage, PiaPacketV16, decode_messages_v16, encode_messages_v16
from pokemon_trade.games.frlg.pia.peer import PiaPeer
from pokemon_trade.games.frlg.pia.reliable import (
    RELIABLE_APP_DATA,
    RELIABLE_INITIALIZED,
    RELIABLE_MESSAGE_END,
    RELIABLE_MESSAGE_START,
    ReliableWireFrame,
)
from pokemon_trade.games.frlg.pia.session import PiaProtocol, PiaSession, PiaSessionPhase
from pokemon_trade.games.frlg.pia.wire import FrlgPiaWire
from pokemon_trade.games.frlg.trade.model import FrlgCommand, FrlgCommandKind, FrlgWireSignalKind
from pokemon_trade.transport.base import Datagram, ParticipantAddress, SessionContext


SSID = bytes(range(16))
KEY = bytes(range(16))
LOCAL_IP = "169.254.1.2"
HOST_IP = "169.254.1.1"
LOCAL_VARIABLE_ID = 0x1111
HOST_VARIABLE_ID = 0x2222


class DatagramScript:
    def __init__(self, payloads: list[bytes]) -> None:
        self.session = SessionContext(
            SSID,
            0x01006FA0233F8000,
            1,
            88,
            "fake0",
            ParticipantAddress(LOCAL_IP, "02:00:00:00:00:02"),
            ParticipantAddress(HOST_IP, "02:00:00:00:00:01"),
            "169.254.1.255",
        )
        self._payloads = iter(payloads)
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    async def send(self, payload: bytes, destination: tuple[str, int]) -> None:
        self.sent.append((payload, destination))

    async def receive(self) -> Datagram:
        try:
            payload = next(self._payloads)
        except StopIteration:
            await trio.sleep_forever()
            raise AssertionError("unreachable")
        return Datagram(payload, (HOST_IP, 12345), (LOCAL_IP, 12345), 0.0)

    async def aclose(self) -> None:
        return None


def encrypted(protocol: PiaProtocol, payload: bytes, *, packet_id: int) -> bytes:
    application = encode_messages_v16((PiaMessage(0, protocol, 0, 0, payload),))
    return encrypt_frlg_v16(
        ssid=SSID,
        game_key=KEY,
        source_ip=HOST_IP,
        destination_variable_id=LOCAL_VARIABLE_ID,
        source_variable_id=HOST_VARIABLE_ID,
        packet_id=packet_id,
        nonce=packet_id.to_bytes(8, "big"),
        application=application,
        footer=LOCAL_VARIABLE_ID.to_bytes(2, "big"),
    ).encode()


class FrlgPiaRfuDriverTest(unittest.TestCase):
    def test_negotiates_to_rfu_accept_without_permitting_menu_input(self) -> None:
        async def scenario() -> None:
            connect_id = b"\x12\x34"
            net_body = (1).to_bytes(4, "big") + HOST_VARIABLE_ID.to_bytes(2, "big") + b"HOSTID"
            net_request = b"\0\x11" + len(net_body).to_bytes(2, "big") + net_body
            accepted = ControlFrame(FrameType.ACCEPT, b"\0\0" + connect_id).encode()
            accepted_reliable = ReliableWireFrame(
                RELIABLE_APP_DATA | RELIABLE_MESSAGE_START | RELIABLE_MESSAGE_END | RELIABLE_INITIALIZED,
                1,
                1,
                accepted,
            ).encode()
            host_uni_reliable = ReliableWireFrame(
                RELIABLE_APP_DATA | RELIABLE_MESSAGE_START | RELIABLE_MESSAGE_END,
                2,
                1,
                b"WT\x19\0\x01\0\0\0\x11\0\0\0" + (int(4) << 14).to_bytes(3, "little") + bytes(14),
            ).encode()
            transport = DatagramScript(
                [
                    encrypted(PiaProtocol.NET, net_request, packet_id=1),
                    encrypted(PiaProtocol.SESSION, b"\x05", packet_id=2),
                    encrypted(PiaProtocol.RELIABLE, accepted_reliable, packet_id=3),
                    encrypted(PiaProtocol.RELIABLE, host_uni_reliable, packet_id=4),
                ]
            )
            driver = FrlgPiaRfuDriver(
                transport,
                FrlgLiveWireConfig(
                    KEY,
                    b"LOCAL!",
                    "EMU",
                    connect_id,
                    bytes(range(26)),
                    random_nonce=bytes(4),
                ),
            )
            await driver.start()

            self.assertEqual((await driver.receive()).kind, FrlgWireSignalKind.PEER_CONNECTED)
            host_uni = await transport.receive()
            driver._ingest(host_uni.payload, HOST_IP)
            self.assertTrue(driver._host_uni_entered)
            self.assertFalse(driver._signals)
            self.assertTrue(transport.sent)
            self.assertTrue(all(destination == (HOST_IP, 12345) for _, destination in transport.sent))
            with self.assertRaises(ProtocolStateError):
                await driver.send(FrlgCommand(FrlgCommandKind.OFFER_SLOT, 0))
            await driver.aclose()

        trio.run(scenario)

    def test_rejects_invalid_local_secret_shapes(self) -> None:
        with self.assertRaises(ValueError):
            FrlgLiveWireConfig(b"short", b"LOCAL!", "EMU", b"\0\0", b"")
        with self.assertRaises(ValueError):
            FrlgLiveWireConfig(KEY, b"bad", "EMU", b"\0\0", b"")

    def test_retries_the_session_join_before_any_host_traffic(self) -> None:
        async def scenario() -> None:
            transport = DatagramScript([])
            driver = FrlgPiaRfuDriver(
                transport,
                FrlgLiveWireConfig(KEY, b"LOCAL!", "EMU", b"\x12\x34", bytes(range(26))),
            )
            await driver.start()
            self.assertEqual(len(driver._wire.drain_datagrams()), 1)  # type: ignore[union-attr]
            driver._next_pia_join_at = 0.0
            driver._link_tick()
            self.assertEqual(len(driver._wire.drain_datagrams()), 1)  # type: ignore[union-attr]
            self.assertGreater(driver._next_pia_join_at, PIA_JOIN_RETRY_SECONDS)  # type: ignore[arg-type]

        trio.run(scenario)

    def test_stops_bootstrap_retries_after_learning_the_host_id(self) -> None:
        async def scenario() -> None:
            transport = DatagramScript([])
            driver = FrlgPiaRfuDriver(
                transport,
                FrlgLiveWireConfig(KEY, b"LOCAL!", "EMU", b"\x12\x34", bytes(range(26))),
            )
            await driver.start()
            driver._wire.drain_datagrams()  # type: ignore[union-attr]
            driver._wire.peer.session.host_variable_id = 2  # type: ignore[union-attr]
            driver._next_pia_join_at = 0.0
            driver._link_tick()
            self.assertEqual(driver._wire.drain_datagrams(), ())  # type: ignore[union-attr]

        trio.run(scenario)

    def test_ready_link_emits_an_idle_uni_slot_on_each_quiet_vblank(self) -> None:
        transport = DatagramScript([])
        driver = FrlgPiaRfuDriver(
            transport,
            FrlgLiveWireConfig(KEY, b"LOCAL!", "EMU", b"\x12\x34", bytes(range(26))),
        )
        link = driver._link = RfuFollowerLink(b"\x12\x34", bytes(range(26)))
        link._accepted = True  # type: ignore[attr-defined]
        link._host_uni_seen = True  # type: ignore[attr-defined]
        link._ni.state = NiState.DONE
        driver._link_started = True
        driver._wire = FrlgPiaWire(PiaPeer(PiaSession(local_constant_id=b"LOCAL!", local_ip=LOCAL_IP, player_name="EMU", random_nonce=bytes(4), app_version=88), ssid=SSID, game_key=KEY, local_ip=LOCAL_IP))
        driver._wire.peer.session.local_variable_id = LOCAL_VARIABLE_ID
        driver._wire.peer.session.host_variable_id = HOST_VARIABLE_ID
        driver._wire.peer.session.phase = PiaSessionPhase.CONNECTED
        driver._slot_credit = 1

        driver._link_tick()
        queued = next(iter(driver._wire._unacknowledged.values()))[0].payload  # type: ignore[union-attr]
        self.assertEqual(queued[:2], b"WT")
        self.assertEqual(queued[12:], uni_slot(RfuSlot.idle()))

    def test_ready_link_does_not_run_ahead_without_a_host_poll(self) -> None:
        transport = DatagramScript([])
        driver = FrlgPiaRfuDriver(
            transport,
            FrlgLiveWireConfig(KEY, b"LOCAL!", "EMU", b"\x12\x34", bytes(range(26))),
        )
        link = driver._link = RfuFollowerLink(b"\x12\x34", bytes(range(26)))
        link._accepted = True  # type: ignore[attr-defined]
        link._host_uni_seen = True  # type: ignore[attr-defined]
        link._ni.state = NiState.DONE
        driver._link_started = True
        driver._wire = FrlgPiaWire(PiaPeer(PiaSession(local_constant_id=b"LOCAL!", local_ip=LOCAL_IP, player_name="EMU", random_nonce=bytes(4), app_version=88), ssid=SSID, game_key=KEY, local_ip=LOCAL_IP))
        driver._wire.peer.session.local_variable_id = LOCAL_VARIABLE_ID
        driver._wire.peer.session.host_variable_id = HOST_VARIABLE_ID
        driver._wire.peer.session.phase = PiaSessionPhase.CONNECTED

        driver._link_tick()

        self.assertEqual(driver._wire._unacknowledged, {})

    def test_late_scheduler_tick_emits_only_one_new_child_slot(self) -> None:
        async def scenario() -> None:
            transport = DatagramScript([])
            driver = FrlgPiaRfuDriver(
                transport,
                FrlgLiveWireConfig(KEY, b"LOCAL!", "EMU", b"\x12\x34", bytes(range(26))),
            )
            await driver.start()
            link = driver._link = RfuFollowerLink(b"\x12\x34", bytes(range(26)))
            link._accepted = True  # type: ignore[attr-defined]
            link._host_uni_seen = True  # type: ignore[attr-defined]
            link._ni.state = NiState.DONE
            driver._link_started = True
            assert driver._wire is not None
            driver._wire.peer.session.local_variable_id = LOCAL_VARIABLE_ID
            driver._wire.peer.session.host_variable_id = HOST_VARIABLE_ID
            driver._wire.peer.session.phase = PiaSessionPhase.CONNECTED
            driver._next_vblank_at = 0.0
            driver._slot_credit = 2

            await driver._advance_vblank_clock()

            self.assertEqual(len(driver._wire._unacknowledged), 1)

        trio.run(scenario)

    def test_timestamp_ack_uses_first_message_slot_in_its_pia_datagram(self) -> None:
        async def scenario() -> None:
            connect_id = b"\x12\x34"
            net_body = (1).to_bytes(4, "big") + HOST_VARIABLE_ID.to_bytes(2, "big") + b"HOSTID"
            net_request = b"\0\x11" + len(net_body).to_bytes(2, "big") + net_body
            accepted = ReliableWireFrame(
                RELIABLE_APP_DATA | RELIABLE_MESSAGE_START | RELIABLE_MESSAGE_END | RELIABLE_INITIALIZED,
                1,
                1,
                ControlFrame(FrameType.ACCEPT, b"\0\0" + connect_id).encode(),
            ).encode()
            host_slot = ReliableWireFrame(
                RELIABLE_APP_DATA | RELIABLE_MESSAGE_START | RELIABLE_MESSAGE_END,
                2,
                1,
                b"WT\x05\0\x01\0\0\0\x01",
            ).encode()
            transport = DatagramScript([])
            driver = FrlgPiaRfuDriver(
                transport,
                FrlgLiveWireConfig(KEY, b"LOCAL!", "EMU", connect_id, bytes(range(26))),
            )
            await driver.start()
            driver._ingest(encrypted(PiaProtocol.NET, net_request, packet_id=1), HOST_IP)
            driver._ingest(encrypted(PiaProtocol.SESSION, b"\x05", packet_id=2), HOST_IP)
            driver._ingest(encrypted(PiaProtocol.RELIABLE, accepted, packet_id=3), HOST_IP)
            driver._ingest(encrypted(PiaProtocol.RELIABLE, host_slot, packet_id=4), HOST_IP)
            await driver._flush()

            acknowledgements = []
            for packet_bytes, _ in transport.sent:
                packet = PiaPacketV16.parse(packet_bytes)
                application, _ = decrypt_frlg_v16(packet, SSID, KEY, LOCAL_IP)
                for message in decode_messages_v16(application):
                    if message.protocol_type != PiaProtocol.RELIABLE:
                        continue
                    frame = ReliableWireFrame.parse(message.payload)
                    if frame.payload[:2] == b"WK":
                        acknowledgements.append(frame.payload)
            self.assertEqual(len(acknowledgements), 1)
            self.assertEqual(int.from_bytes(acknowledgements[0][8:12], "little"), 1)
            await driver.aclose()

        trio.run(scenario)
