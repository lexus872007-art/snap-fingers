#!/usr/bin/env python3
# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Набор реальных звуков для проверки детектора: открытые записи CC0 с freesound.org (прослушки hq.mp3 по прямым
ссылкам с поиска, фильтр лицензии «Creative Commons 0»). Перевод в wav 16 кГц моно (ffmpeg).

    python3 eval/fetch_sounds.py ~/shchelchok_build/data        (сервер 2; ~200-400 МБ)

Результат: data/wav/<класс>/<id>.wav и data/sources.csv (класс, id, автор, лицензия, ссылка) - для README.
"""
import csv
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

QUERIES = {
    "snap": ["finger snap", "finger snapping", "snapping fingers", "snap fingers", "finger snaps", "fingersnap"],
    "clap": ["hand clap", "single clap", "clap hands", "clapping", "applause small"],
    "keyboard": ["keyboard typing", "typing laptop", "mechanical keyboard", "typing computer", "keyboard keys"],
    "mouse": ["mouse click", "computer mouse"],
    "knock": ["knock table", "knocking wood", "desk tap", "table hit", "knock door"],
    "speech": ["speech", "talking", "conversation", "man speaking", "woman speaking", "reading aloud",
               "russian speech", "podcast voice"],
    "music": ["music loop", "piano", "acoustic guitar", "drum loop", "pop music", "electronic beat"],
    "ambience": ["room tone", "office ambience", "computer fan", "cafe ambience"],
    "other": ["pen click", "tongue click", "cup on table", "cough", "paper", "door close", "spoon glass"],
}
PAGES = {"snap": 4, "speech": 2, "music": 2, "keyboard": 2, "clap": 2}
MAXDUR = {"snap": 60, "clap": 60, "keyboard": 180, "mouse": 120, "knock": 60, "speech": 300, "music": 300,
          "ambience": 300, "other": 60}


LIMIT = {"speech": 40, "music": 30, "ambience": 16, "keyboard": 40, "mouse": 20, "knock": 30, "other": 40,
         "clap": 130, "snap": 200}
HEAD_BYTES = {"speech": 1500000, "music": 1500000, "ambience": 1500000, "keyboard": 1000000}   # первые ~60-90 с


def get(url, nbytes=None):
    h = {"User-Agent": "Mozilla/5.0 (research; CC0 previews)"}
    if nbytes:
        h["Range"] = f"bytes=0-{nbytes}"
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=40).read()


def search(q, page):
    url = ("https://freesound.org/search/?" + urllib.parse.urlencode(
        {"q": q, "f": 'license:"Creative Commons 0"', "page": page}))
    html = get(url).decode("utf-8", "replace")
    prev = {m.group(2): m.group(1) for m in re.finditer(r"(previews/\d+/(\d+)_\d+)-lq\.mp3", html)}
    users = {m.group(2): m.group(1) for m in re.finditer(r"/people/([^/]+)/sounds/(\d+)/", html)}
    return [(sid, users.get(sid, "?"), "https://cdn.freesound.org/" + p + "-hq.mp3") for sid, p in prev.items()]


def main():
    out = sys.argv[1]
    raw, wav = os.path.join(out, "raw"), os.path.join(out, "wav")
    rows, seen = [], set()
    only = sys.argv[2].split(",") if len(sys.argv) > 2 else list(QUERIES)
    for cls, qs in QUERIES.items():
        if cls not in only:
            continue
        os.makedirs(os.path.join(wav, cls), exist_ok=True)
        for q in qs:
            for page in range(1, PAGES.get(cls, 1) + 1):
                try:
                    res = search(q, page)
                except Exception as e:  # noqa: BLE001
                    print("поиск", q, page, e, flush=True)
                    continue
                time.sleep(1.0)
                for sid, user, url in res:
                    if sum(1 for r in rows if r[0] == cls) >= LIMIT.get(cls, 50):
                        break
                    if sid in seen:
                        continue
                    seen.add(sid)
                    mp3 = os.path.join(raw, f"{sid}.mp3")
                    w = os.path.join(wav, cls, f"{sid}.wav")
                    if os.path.exists(w):
                        rows.append((cls, sid, user, "CC0", f"https://freesound.org/people/{user}/sounds/{sid}/", q))
                        continue
                    try:
                        if not os.path.exists(mp3):
                            data = get(url, HEAD_BYTES.get(cls))
                            os.makedirs(raw, exist_ok=True)
                            open(mp3, "wb").write(data)
                            time.sleep(0.4)
                        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", mp3, "-t",
                                        str(MAXDUR[cls]), "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", w],
                                       check=True)
                        os.remove(mp3)
                    except Exception as e:  # noqa: BLE001
                        print("файл", sid, e, flush=True)
                        continue
                    rows.append((cls, sid, user, "CC0", f"https://freesound.org/people/{user}/sounds/{sid}/", q))
                print(cls, q, page, "всего", len(rows), flush=True)
    tag = sys.argv[3] if len(sys.argv) > 3 else ""
    with open(os.path.join(out, f"sources{tag}.csv"), "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("class", "id", "author", "license", "url", "query")] + rows)
    print("ГОТОВО", len(rows))


if __name__ == "__main__":
    main()
