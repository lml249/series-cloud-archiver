from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from .models import EmbyEvidence, FileSystemSeries


class EmbyClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _get(self, path: str, query: Dict[str, str]) -> Dict[str, object]:
        query = dict(query)
        query["api_key"] = self.api_key
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(query)}"
        with urllib.request.urlopen(url, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))

    def series_items(self) -> List[Dict[str, object]]:
        payload = self._get(
            "/emby/Items",
            {
                "Recursive": "true",
                "IncludeItemTypes": "Series",
                "Fields": "Path,RecursiveItemCount,ProviderIds",
            },
        )
        return list(payload.get("Items") or [])


def fetch_emby_evidence(base_url: str, api_key: str) -> List[EmbyEvidence]:
    client = EmbyClient(base_url, api_key)
    evidence: List[EmbyEvidence] = []
    for item in client.series_items():
        evidence.append(
            EmbyEvidence(
                name=str(item.get("Name") or ""),
                item_id=str(item.get("Id") or ""),
                path=str(item.get("Path") or ""),
                episode_count=int(item.get("RecursiveItemCount") or item.get("ChildCount") or 0),
                matched=False,
            )
        )
    return evidence


def match_emby(series: FileSystemSeries, items: List[EmbyEvidence]) -> Optional[EmbyEvidence]:
    series_path = series.path.rstrip("/")
    best: Optional[EmbyEvidence] = None
    best_score = 0
    for item in items:
        item_path = item.path.rstrip("/")
        score = 0
        if item_path and (series_path == item_path or series_path.startswith(item_path + "/") or item_path.startswith(series_path + "/")):
            score = 100
        elif item.name and item.name.lower() in series.title.lower():
            score = 35
        elif series.title.lower() in item.name.lower():
            score = 30
        if score > best_score:
            best_score = score
            best = item
    if best:
        return EmbyEvidence(
            name=best.name,
            item_id=best.item_id,
            path=best.path,
            episode_count=best.episode_count,
            matched=True,
        )
    return None

