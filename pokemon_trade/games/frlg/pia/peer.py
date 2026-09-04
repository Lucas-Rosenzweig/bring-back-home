"""PIA v16 datagram peer: crypto, message tiling, and session-control replies."""

from __future__ import annotations

import secrets
from collections.abc import Callable

from pokemon_trade.errors import MalformedDatagramError
from pokemon_trade.games.frlg.pia.crypto import decrypt_frlg_v16, encrypt_frlg_v16
from pokemon_trade.games.frlg.pia.packet import PiaMessage as PacketMessage
from pokemon_trade.games.frlg.pia.packet import PiaPacketV16, decode_messages_v16, encode_messages_v16
from pokemon_trade.games.frlg.pia.session import PiaMessage, PiaOutbound, PiaProtocol, PiaSession

FRLG_PIA_COMPRESS_MIN = 62


class PiaPeer:
    """Translate encrypted UDP datagrams into PIA messages and session replies.

    Higher FRLG layers consume the returned non-session messages. Session traffic
    is handled here, so it cannot leak variable-ID or crypto details upward.
    """

    def __init__(
        self,
        session: PiaSession,
        *,
        ssid: bytes,
        game_key: bytes,
        local_ip: str,
        nonce_source: Callable[[int], bytes] | None = None,
    ) -> None:
        self.session = session
        self.ssid = bytes(ssid)
        self.game_key = bytes(game_key)
        self.local_ip = local_ip
        self._nonce_source = nonce_source
        # PIA compares the eight-byte header nonce as a monotonic counter.  A
        # fresh random value per packet is therefore not interchangeable with
        # a random counter seed: roughly half of those values move backwards
        # and are discarded before Reliable sees them.
        self._nonce_counter = int.from_bytes(secrets.token_bytes(8), "big") or 1
        self._packet_ids: dict[int, int] = {}
        self._pending_outbounds: list[PiaOutbound] = []

    def receive(self, datagram: bytes, source_ip: str) -> tuple[PiaMessage, ...]:
        packet = PiaPacketV16.parse(datagram)
        application, footer = decrypt_frlg_v16(packet, self.ssid, self.game_key, source_ip)
        if len(footer) % 2:
            raise MalformedDatagramError("PIA v16 recipient footer has an odd size")
        incoming: list[PiaMessage] = []
        for message in decode_messages_v16(application):
            try:
                protocol = PiaProtocol(message.protocol_type)
            except ValueError:
                continue
            decoded = PiaMessage(protocol, message.payload)
            replies = self.session.ingest(
                packet.destination_variable_id,
                packet.source_variable_id,
                decoded,
            )
            self._pending_outbounds.extend(replies)
            if protocol not in {PiaProtocol.NET, PiaProtocol.SESSION, PiaProtocol.RTT}:
                incoming.append(decoded)
        return tuple(incoming)

    def begin(self, host_constant_id: bytes, local_variable_id: int) -> None:
        """Queue the initial v6 Session(join) message for the LDN host."""
        self._pending_outbounds.append(self.session.begin(host_constant_id, local_variable_id))

    def drain(self) -> tuple[bytes, ...]:
        packets = tuple(self._encode(outbound) for outbound in self._pending_outbounds)
        self._pending_outbounds.clear()
        return packets

    def queue_data(self, protocol: PiaProtocol, payload: bytes) -> None:
        """Queue established unicast application data to the learned PIA host."""
        if self.session.host_variable_id is None or self.session.local_variable_id is None:
            raise MalformedDatagramError("PIA application data attempted before host IDs were learned")
        self._pending_outbounds.append(
            PiaOutbound(
                PiaMessage(protocol, payload),
                self.session.host_variable_id,
                self.session.local_variable_id,
                self.session.host_variable_id,
            )
        )

    def encode_data_batch(
        self,
        protocol: PiaProtocol,
        payloads: tuple[bytes, ...],
        *,
        message_flags: tuple[int, ...] | None = None,
    ) -> bytes:
        """Encode one established PIA datagram containing ordered protocol frames."""
        if not payloads:
            raise ValueError("PIA data batch cannot be empty")
        flags = message_flags or (0,) * len(payloads)
        if len(flags) != len(payloads):
            raise ValueError("PIA data batch flags must match its payload count")
        if self.session.host_variable_id is None or self.session.local_variable_id is None:
            raise MalformedDatagramError("PIA application data attempted before host IDs were learned")
        destination = self.session.host_variable_id
        messages = tuple(
            PacketMessage(message_flag, int(protocol), 0, 0, bytes(payload))
            for payload, message_flag in zip(payloads, flags, strict=True)
        )
        application = encode_messages_v16(messages)
        packet = encrypt_frlg_v16(
            ssid=self.ssid,
            game_key=self.game_key,
            source_ip=self.local_ip,
            destination_variable_id=destination,
            source_variable_id=self.session.local_variable_id,
            packet_id=self._next_packet_id(destination),
            nonce=self._next_nonce(),
            application=application,
            footer=destination.to_bytes(2, "big"),
            compressed=len(application) >= FRLG_PIA_COMPRESS_MIN,
        )
        return packet.encode()

    def _encode(self, outbound: PiaOutbound) -> bytes:
        destination = outbound.destination_variable_id
        packet_id = 0 if outbound.establishing else self._next_packet_id(destination)
        message = PacketMessage(0, int(outbound.message.protocol), 0, 0, outbound.message.payload)
        packet = encrypt_frlg_v16(
            ssid=self.ssid,
            game_key=self.game_key,
            source_ip=self.local_ip,
            destination_variable_id=destination,
            source_variable_id=outbound.source_variable_id,
            packet_id=packet_id,
            nonce=self._next_nonce(),
            application=encode_messages_v16((message,)),
            footer=(outbound.footer_variable_id.to_bytes(2, "big") if outbound.footer_variable_id is not None else b""),
            compressed=outbound.compressed,
            establishing=outbound.establishing,
        )
        return packet.encode()

    def _next_packet_id(self, destination: int) -> int:
        value = self._packet_ids.get(destination, 1)
        self._packet_ids[destination] = 1 if value == 0xFFFF else value + 1
        return value

    def _next_nonce(self) -> bytes:
        if self._nonce_source is not None:
            nonce = self._nonce_source(8)
            if len(nonce) != 8:
                raise ValueError("FRLG PIA packet nonce source must return eight bytes")
            return bytes(nonce)
        nonce = self._nonce_counter.to_bytes(8, "big")
        self._nonce_counter = ((self._nonce_counter + 1) & 0xFFFFFFFFFFFFFFFF) or 1
        return nonce
