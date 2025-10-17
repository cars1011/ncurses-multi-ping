#!/usr/bin/env python3
"""
ncurses_multi_ping.py

Ein einfaches ncurses-basiertes Skript (Python) zum gleichzeitigen Pingen mehrerer Hosts
und zur Anzeige des Status (UP/DOWN) inkl. RTT.

Usage:
    python3 ncurses_multi_ping.py host1 host2 host3

Tasten:
    q - Beenden
    p - Pause / Resume der automatischen Pings
    u - Sofortige Aktualisierung (erneutes Pingen)
    +/- - Ping-Intervall erhöhen/verringern (Sekunden)

Benötigt: Python 3.8+ (Linux/Unix). Das Skript ruft das System-ping auf (ipv4).
"""

import sys
import asyncio
import curses
import shutil
from datetime import datetime
from typing import Optional, Tuple

DEFAULT_INTERVAL = 2.0  # Sekunden zwischen automatischen Pings
PING_TIMEOUT = 1  # Sekunden (für ping -W)


class HostStatus:
    def __init__(self, host):
        self.host = host
        self.last_result = None  # True/False/None
        self.last_rtt = None
        self.last_time = None


async def ping_host(host: str) -> Tuple[bool, Optional[float]]:
    """Pinge `host` einmal. Liefert (is_up, rtt_ms_or_None).
    Benutzt system 'ping' (ipv4): ping -c 1 -W PING_TIMEOUT host
    """
    ping_cmd = shutil.which("ping")
    if not ping_cmd:
        raise RuntimeError("System 'ping' nicht gefunden")

    proc = await asyncio.create_subprocess_exec(
        ping_cmd, "-c", "1", "-W", str(PING_TIMEOUT), host,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=PING_TIMEOUT + 2)
    except asyncio.TimeoutError:
        proc.kill()
        return False, None

    out = stdout.decode(errors="ignore")
    if "time=" in out:
        try:
            idx = out.index("time=") + 5
            rest = out[idx: idx + 20]
            rtt_str = rest.split()[0]
            rtt = float(rtt_str)
            return True, rtt
        except Exception:
            return True, None
    else:
        return False, None


async def worker(host_status: HostStatus, interval_event: asyncio.Event, pause_flag: dict, interval_ref: dict):
    """Läuft permanent und pingt den Host in regelmäßigen Abständen."""
    while True:
        if not pause_flag['paused']:
            try:
                up, rtt = await ping_host(host_status.host)
            except Exception:
                up, rtt = False, None
            host_status.last_result = up
            host_status.last_rtt = rtt
            host_status.last_time = datetime.now()
        try:
            await asyncio.wait_for(interval_event.wait(), timeout=interval_ref['val'])
            interval_event.clear()
        except asyncio.TimeoutError:
            pass


async def refresher(stdscr, hosts, pause_flag, interval_ref):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)  # up
    curses.init_pair(2, curses.COLOR_RED, -1)    # down
    curses.init_pair(3, curses.COLOR_YELLOW, -1) # unknown
    curses.init_pair(4, curses.COLOR_CYAN, -1)   # header

    interval_event = asyncio.Event()

    tasks = [asyncio.create_task(worker(hs, interval_event, pause_flag, interval_ref)) for hs in hosts]

    try:
        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            header = f"Multi-Ping — {len(hosts)} Hosts — Intervall: {interval_ref['val']:.1f}s — {'PAUSED' if pause_flag['paused'] else 'RUNNING'}"
            stdscr.addstr(0, 0, header[:w-1], curses.color_pair(4) | curses.A_BOLD)
            stdscr.addstr(1, 0, "Tasten: q=Quit p=Pause u=Update +/-=Intervall", curses.A_DIM)

            stdscr.addstr(3, 0, f"{'Host':30} {'Status':8} {'RTT(ms)':8} {'Letztes Update':20}")
            stdscr.hline(4, 0, '-', w)

            for i, hs in enumerate(hosts):
                y = 5 + i
                if y >= h - 1:
                    break
                host_str = hs.host[:30].ljust(30)
                if hs.last_result is None:
                    status = 'UNKNOWN'
                    color = curses.color_pair(3)
                    rtt_str = '-'
                    ts = '-'
                elif hs.last_result:
                    status = 'UP'
                    color = curses.color_pair(1)
                    rtt_str = f"{hs.last_rtt:.1f}" if hs.last_rtt is not None else '-'
                    ts = hs.last_time.strftime('%H:%M:%S') if hs.last_time else '-'
                else:
                    status = 'DOWN'
                    color = curses.color_pair(2)
                    rtt_str = '-'
                    ts = hs.last_time.strftime('%H:%M:%S') if hs.last_time else '-'

                stdscr.addstr(y, 0, host_str)
                stdscr.addstr(y, 31, status.ljust(8), color | curses.A_BOLD)
                stdscr.addstr(y, 40, rtt_str.rjust(8))
                stdscr.addstr(y, 49, ts.rjust(20))

            stdscr.refresh()

            stdscr.timeout(200)
            try:
                key = stdscr.getch()
            except KeyboardInterrupt:
                key = ord('q')

            if key == -1:
                await asyncio.sleep(0)
                continue
            if key in (ord('q'), ord('Q')):
                break
            elif key in (ord('p'), ord('P')):
                pause_flag['paused'] = not pause_flag['paused']
            elif key in (ord('u'), ord('U')):
                interval_event.set()
            elif key == ord('+'):
                interval_ref['val'] = max(0.2, interval_ref['val'] - 0.2)
            elif key == ord('-'):
                interval_ref['val'] = interval_ref['val'] + 0.2

            await asyncio.sleep(0)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def main(stdscr, host_list):
    hosts = [HostStatus(h) for h in host_list]
    pause_flag = {'paused': False}
    interval_ref = {'val': DEFAULT_INTERVAL}

    asyncio.run(refresher(stdscr, hosts, pause_flag, interval_ref))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 ncurses_multi_ping.py host1 host2 ...")
        sys.exit(1)
    host_list = sys.argv[1:]
    curses.wrapper(main, host_list)
