import unittest
from hashlib import sha256

from Crypto.Cipher import AES

from IEEE80211.ldn import parse_ldn_advertisement
from ldn_client import decode_network, is_joinable
from ldn_protocol import (
    ACCEPT_ALL,
    ACCEPT_NONE,
    KeyDerivation,
    MACAddress,
    NetworkInfo,
    ParticipantInfo,
    encode_advertisement_gcm,
    encode_authentication_request,
    validate_authentication_response,
)
from Wifi.LdnStation import infer_local_participant

COMMUNICATION_ID = 0x0100A3D008C5C000


def encrypted_advertisement() -> tuple[bytes, dict[str, bytes]]:
    keys = {
        "master_key_12": b"\x11" * 16,
        "aes_kek_generation_source": b"\x22" * 16,
        "aes_key_generation_source": b"\x33" * 16,
    }
    network = NetworkInfo(3)
    network.address = MACAddress.parse("02:00:00:00:00:01")
    network.channel = 6
    network.band = 2
    network.local_communication_id = COMMUNICATION_ID
    network.scene_id = 4
    network.ssid = bytes(range(16))
    network.version = 4
    network.server_random = b"\x44" * 16
    network.app_version = 21
    network.accept_policy = ACCEPT_ALL
    network.max_participants = 2
    network.num_participants = 1
    network.participants = [ParticipantInfo() for _ in range(8)]
    network.participants[0].connected = True
    network.participants[0].ip_address = "169.254.80.1"
    network.participants[0].mac_address = network.address
    network.application_data = b"test"
    network.challenge = 123
    network.nonce = b"\x55" * 4

    action = encode_advertisement_gcm(network, keys)
    raw = (
        b"\xd0\x00"
        + b"\x00\x00"
        + b"\xff" * 6
        + bytes(network.address)
        + bytes(network.address)
        + b"\x00\x00"
        + action
    )
    return raw, keys


class LdnClientTest(unittest.TestCase):
    def test_infers_first_free_participant_when_managed_mode_filters_ads(self) -> None:
        raw, keys = encrypted_advertisement()
        advertisement = parse_ldn_advertisement(raw)
        assert advertisement is not None
        network = decode_network(advertisement, 6, keys, protocols=(3,))
        local_mac = MACAddress.parse("A4:B1:C1:98:6E:FE")

        inferred, slot = infer_local_participant(network, local_mac, b"SVPC", 21)

        self.assertEqual(slot, 1)
        self.assertEqual(inferred.num_participants, 2)
        self.assertEqual(inferred.participants[1].ip_address, "169.254.80.2")
        self.assertEqual(inferred.participants[1].mac_address, local_mac)
        self.assertEqual(inferred.participants[1].name, b"SVPC")
        self.assertFalse(network.participants[1].connected)

    def test_inference_skips_an_occupied_participant_slot(self) -> None:
        raw, keys = encrypted_advertisement()
        advertisement = parse_ldn_advertisement(raw)
        assert advertisement is not None
        network = decode_network(advertisement, 6, keys, protocols=(3,))
        network.max_participants = 4
        network.participants[1] = ParticipantInfo(
            "169.254.80.2",
            MACAddress.parse("02:00:00:00:00:02"),
            True,
            b"PEER",
            21,
            0,
        )

        inferred, slot = infer_local_participant(
            network,
            MACAddress.parse("A4:B1:C1:98:6E:FE"),
            b"SVPC",
            21,
        )

        self.assertEqual(slot, 2)
        self.assertEqual(inferred.participants[2].ip_address, "169.254.80.3")

    def test_matches_reference_binary_vectors(self) -> None:
        raw, keys = encrypted_advertisement()
        advertisement = parse_ldn_advertisement(raw)
        assert advertisement is not None
        network = decode_network(advertisement, 6, keys, protocols=(3,))

        authentication = encode_authentication_request(
            network,
            keys,
            bytes.fromhex("66" * 16),
            b"SVPC",
            21,
            0x1122334455667788,
            0x8877665544332211,
        )

        self.assertEqual(
            sha256(raw[24:]).hexdigest(),
            "fd644b89e3b6a16c3ae2dc918cecd547dcf5a01fcfe6ec4dd86bb91e68c78aaf",
        )
        self.assertEqual(
            sha256(authentication).hexdigest(),
            "45eaafec0867f9c0719e6a426ff314f15767c9d2b599c67cb3587e6d7575ee2b",
        )

    def test_validates_encrypted_authentication_response(self) -> None:
        raw, keys = encrypted_advertisement()
        advertisement = parse_ldn_advertisement(raw)
        assert advertisement is not None
        network = decode_network(advertisement, 6, keys, protocols=(3,))
        client_random = bytes.fromhex("66" * 16)
        payload = bytes(0x84)
        size = len(payload)
        network_id = (
            network.local_communication_id.to_bytes(8, "little")
            + bytes(2)
            + network.scene_id.to_bytes(2, "little")
            + bytes(4)
            + network.ssid
        )
        header = (
            bytes([network.version, size, 0, 1, 0, 1, 0, 0])
            + network_id
            + network.server_random
            + client_random
        )
        key = KeyDerivation(keys, 3).authentication_key(client_random)
        cipher = AES.new(key, AES.MODE_GCM, nonce=header[:12])
        cipher.update(header)
        ciphertext, tag = cipher.encrypt_and_digest(payload)
        response = b"\x00\x22\xaa\x01\x02\x00" + header + tag + ciphertext

        validate_authentication_response(response, network, keys, client_random)

        corrupted = response[:-1] + bytes([response[-1] ^ 1])
        with self.assertRaises(ValueError):
            validate_authentication_response(corrupted, network, keys, client_random)

    def test_decrypts_captured_advertisement_into_network_info(self) -> None:
        raw, keys = encrypted_advertisement()
        advertisement = parse_ldn_advertisement(raw)
        assert advertisement is not None

        network = decode_network(advertisement, 6, keys, protocols=(3,))

        self.assertEqual(network.local_communication_id, COMMUNICATION_ID)
        self.assertEqual(network.scene_id, 4)
        self.assertEqual(network.ssid, bytes(range(16)))
        self.assertEqual(network.server_random, b"\x44" * 16)
        self.assertEqual(network.application_data, b"test")
        self.assertEqual(str(network.address), "02:00:00:00:00:01")

    def test_checks_target_capacity_and_accept_policy(self) -> None:
        raw, keys = encrypted_advertisement()
        advertisement = parse_ldn_advertisement(raw)
        assert advertisement is not None
        network = decode_network(advertisement, 6, keys, protocols=(3,))

        self.assertTrue(is_joinable(network, COMMUNICATION_ID, 4))
        self.assertTrue(is_joinable(network))
        network.accept_policy = ACCEPT_NONE
        self.assertFalse(is_joinable(network, COMMUNICATION_ID, 4))
        network.accept_policy = ACCEPT_ALL
        network.num_participants = network.max_participants
        self.assertFalse(is_joinable(network, COMMUNICATION_ID, 4))


if __name__ == "__main__":
    unittest.main()
