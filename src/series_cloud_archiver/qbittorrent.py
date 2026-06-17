from __future__ import annotations

import json
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from typing import Dict, List, Optional

from .models import FileSystemSeries, QBTorrentEvidence


UP_STATES = {
    "uploading",
    "stalledUP",
    "pausedUP",
    "queuedUP",
    "forcedUP",
    "checkingUP",
}


class QBClient:
    def __init__(self, base_url: str, user: str = "", qb_pass: str = "", timeout: int = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.qb_pass = qb_pass
        self.timeout = timeout
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def login(self) -> None:
        if not self.user and not self.qb_pass:
            return
        body = urllib.parse.urlencode({"username": self.user, "password": self.qb_pass}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/v2/auth/login",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with self.opener.open(request, timeout=self.timeout) as response:
            payload = response.read().decode("utf-8", "replace").strip()
        if payload.rstrip(".").lower() != "ok":
            raise RuntimeError("qBittorrent login failed")

    def torrents(self) -> List[Dict[str, object]]:
        request = urllib.request.Request(f"{self.base_url}/api/v2/torrents/info")
        with self.opener.open(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))


def fetch_qb_evidence(base_url: str, user: str = "", qb_pass: str = "") -> List[QBTorrentEvidence]:
    client = QBClient(base_url=base_url, user=user, qb_pass=qb_pass)
    client.login()
    evidence: List[QBTorrentEvidence] = []
    for item in client.torrents():
        seeding_seconds = int(item.get("seeding_time") or 0)
        evidence.append(
            QBTorrentEvidence(
                name=str(item.get("name") or ""),
                hash=str(item.get("hash") or ""),
                state=str(item.get("state") or ""),
                save_path=str(item.get("save_path") or ""),
                content_path=str(item.get("content_path") or ""),
                progress=float(item.get("progress") or 0.0),
                seeding_time_seconds=seeding_seconds,
                seed_days=seeding_seconds / 86400.0,
                size_bytes=int(item.get("size") or item.get("total_size") or 0),
            )
        )
    return evidence


def match_torrent(series: FileSystemSeries, torrents: List[QBTorrentEvidence]) -> Optional[QBTorrentEvidence]:
    series_path = series.path.rstrip("/")
    best: Optional[QBTorrentEvidence] = None
    best_score = 0
    for torrent in torrents:
        paths = [torrent.content_path.rstrip("/"), torrent.save_path.rstrip("/")]
        score = 0
        if series_path in paths:
            score = 100
        elif any(path and (series_path.startswith(path + "/") or path.startswith(series_path + "/")) for path in paths):
            score = 80
        elif torrent.name and torrent.name.lower() in series.title.lower():
            score = 40
        elif series.title.lower() in torrent.name.lower():
            score = 35
        if score > best_score:
            best_score = score
            best = torrent
    return best
