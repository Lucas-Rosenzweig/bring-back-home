import signal
from types import FrameType

from IEEE80211.ldn import parse_ldn_advertisement
from Wifi.LinuxMonitor import LinuxMonitor

LDN_CHANNELS = (1, 6, 11, 36, 40, 44, 48)
LDN_DWELL_SECONDS = 0.110


def _terminate(signum: int, frame: FrameType | None) -> None:
    raise SystemExit(128 + signum)


def main() -> None:
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGHUP, _terminate)
    try:
        with LinuxMonitor(
            mon_iface="mon0",
            phy="phy0",
            initial_channel=LDN_CHANNELS[0],
            replace_existing=True,
        ) as monitor:
            print(
                f"Interface {monitor.mon_iface} prête sur le canal "
                f"{monitor.current_channel}",
                flush=True,
            )
            monitor.start_channel_hopping(
                LDN_CHANNELS,
                dwell_seconds=LDN_DWELL_SECONDS,
            )
            print(
                "Channel hopping actif sur "
                + ", ".join(map(str, LDN_CHANNELS))
                + " — en attente d'une advertisement LDN...",
                flush=True,
            )
            locked_channel: int | None = None

            while True:
                capture = monitor.scan()
                if capture is None:
                    continue

                mac_frame, channel = capture
                if channel is None:
                    continue

                try:
                    advertisement = parse_ldn_advertisement(mac_frame)
                except ValueError:
                    continue
                if advertisement is None:
                    continue

                if locked_channel is None:
                    monitor.stop_channel_hopping()
                    monitor.set_channel(channel)
                    locked_channel = channel
                    print(
                        "Advertisement trouvée, verrouillage sur le channel",
                        channel,
                        "!",
                    )
                    advertisement.display()
    except KeyboardInterrupt:
        print("Suppression de l'interface de monitoring et fermeture")


if __name__ == "__main__":
    main()
