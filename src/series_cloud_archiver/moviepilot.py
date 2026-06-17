from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .models import FileSystemSeries, MPSubscriptionEvidence


TV_TYPE = "电视剧"


@dataclass
class MPSubscriptionRecord:
    name: str
    year: str = ""
    media_type: str = ""
    tmdbid: int = 0
    season: int = 0
    total_episode: int = 0
    date: str = ""


class MoviePilotClient:
    def __init__(self, base_url: str, token: str, timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _get(self, path: str, query: Optional[Dict[str, object]] = None) -> object:
        query = dict(query or {})
        if self.token:
            query["token"] = self.token
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            text = response.read().decode("utf-8", "replace")
        return json.loads(text) if text else []

    def current_subscriptions(self) -> List[MPSubscriptionRecord]:
        payload = self._get("/api/v1/subscribe/list")
        return [_record_from_payload(item) for item in _as_list(payload)]

    def subscription_history(self, page_size: int = 100) -> List[MPSubscriptionRecord]:
        records: List[MPSubscriptionRecord] = []
        page = 1
        while True:
            payload = self._get(
                f"/api/v1/subscribe/history/{urllib.parse.quote(TV_TYPE)}",
                {"page": page, "count": page_size},
            )
            page_records = [_record_from_payload(item) for item in _as_list(payload)]
            records.extend(page_records)
            if len(page_records) < page_size:
                break
            page += 1
        return records


def fetch_mp_subscription_evidence(base_url: str, token: str) -> List[MPSubscriptionEvidence]:
    client = MoviePilotClient(base_url, token)
    return build_mp_subscription_evidence(
        current=client.current_subscriptions(),
        history=client.subscription_history(),
    )


def build_mp_subscription_evidence(
    current: Iterable[MPSubscriptionRecord],
    history: Iterable[MPSubscriptionRecord],
) -> List[MPSubscriptionEvidence]:
    current_keys: Set[Tuple[object, ...]] = set()
    current_name_keys: Set[Tuple[object, ...]] = set()
    for record in current:
        if _is_tv(record):
            current_keys.update(_identity_keys(record))
            current_name_keys.add(_name_season_key(record))

    evidence: List[MPSubscriptionEvidence] = []
    seen: Set[Tuple[object, ...]] = set()
    for record in history:
        if not _is_tv(record):
            continue
        current_found = bool(current_keys.intersection(_identity_keys(record))) or _name_season_key(record) in current_name_keys
        if current_found:
            continue
        dedupe_key = _best_identity_key(record)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        evidence.append(
            MPSubscriptionEvidence(
                name=record.name,
                year=record.year,
                media_type=record.media_type,
                tmdbid=record.tmdbid,
                season=record.season,
                total_episode=record.total_episode,
                history_date=record.date,
                current_subscription_found=False,
                matched=False,
            )
        )
    return evidence


def match_mp_subscription(
    series: FileSystemSeries,
    evidence: List[MPSubscriptionEvidence],
) -> Optional[MPSubscriptionEvidence]:
    series_text = _normalize(series.title)
    series_seasons = set(series.signal.seasons)
    best: Optional[MPSubscriptionEvidence] = None
    best_score = 0
    for item in evidence:
        score = 0
        item_name = _normalize(item.name)
        if item_name and item_name in series_text:
            score = 80
        elif item_name and _compact(item_name) in _compact(series_text):
            score = 70
        elif item_name and _word_overlap(item_name, series_text) >= 0.6:
            score = 55
        if score and item.year and item.year in series.title:
            score += 10
        if score and item.season and (not series_seasons or item.season in series_seasons):
            score += 5
        if score > best_score:
            best_score = score
            best = item
    if best and best_score >= 55:
        return MPSubscriptionEvidence(
            name=best.name,
            year=best.year,
            media_type=best.media_type,
            tmdbid=best.tmdbid,
            season=best.season,
            total_episode=best.total_episode,
            history_date=best.history_date,
            current_subscription_found=best.current_subscription_found,
            matched=True,
        )
    return None


def _record_from_payload(item: object) -> MPSubscriptionRecord:
    data = item if isinstance(item, dict) else {}
    return MPSubscriptionRecord(
        name=str(data.get("name") or ""),
        year=str(data.get("year") or ""),
        media_type=str(data.get("type") or ""),
        tmdbid=int(data.get("tmdbid") or 0),
        season=int(data.get("season") or 0),
        total_episode=int(data.get("total_episode") or 0),
        date=str(data.get("date") or data.get("last_update") or ""),
    )


def _as_list(payload: object) -> List[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return list(data["items"])
        if isinstance(payload.get("items"), list):
            return list(payload["items"])
    return []


def _is_tv(record: MPSubscriptionRecord) -> bool:
    return record.media_type == TV_TYPE or record.media_type.lower() in {"tv", "series"}


def _identity_keys(record: MPSubscriptionRecord) -> Set[Tuple[object, ...]]:
    keys: Set[Tuple[object, ...]] = {_name_season_key(record)}
    if record.tmdbid:
        keys.add(("tmdb", record.tmdbid, record.season or 0))
    return keys


def _best_identity_key(record: MPSubscriptionRecord) -> Tuple[object, ...]:
    if record.tmdbid:
        return ("tmdb", record.tmdbid, record.season or 0)
    return _name_season_key(record)


def _name_season_key(record: MPSubscriptionRecord) -> Tuple[object, ...]:
    return ("name", _normalize(record.name), record.year, record.season or 0)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _compact(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.casefold())


def _word_overlap(left: str, right: str) -> float:
    left_words = set(re.findall(r"[0-9a-z\u4e00-\u9fff]+", left.casefold()))
    right_words = set(re.findall(r"[0-9a-z\u4e00-\u9fff]+", right.casefold()))
    if not left_words:
        return 0.0
    return len(left_words & right_words) / len(left_words)
