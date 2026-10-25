# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Названия и авторы записей freesound (для отбора настоящих щелчков пальцами): data/titles.json."""
import json, os, re, sys, time, urllib.request
d = sys.argv[1]; cls = sys.argv[2:] or ["snap"]
path = os.path.join(d, "titles.json")
out = json.load(open(path)) if os.path.exists(path) else {}
for c in cls:
    for f in sorted(os.listdir(os.path.join(d, "wav", c))):
        sid = f[:-4]
        if sid in out:
            continue
        try:
            html = urllib.request.urlopen(urllib.request.Request(f"https://freesound.org/s/{sid}/", headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode("utf-8", "replace")
            t = re.search(r"<title>(.*?)</title>", html, re.S).group(1).strip()
            lic = "CC0" if "publicdomain/zero" in html else ("?" )
            out[sid] = {"class": c, "title": t, "license": lic}
        except Exception as e:
            out[sid] = {"class": c, "title": "?", "err": str(e)}
        time.sleep(1.2)
        json.dump(out, open(path, "w"), ensure_ascii=False, indent=0)
print(len(out))
