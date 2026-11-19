"""Publicador de Reels do Instagram que roda no GitHub Actions (sem depender do PC ligado).

Lê agenda.json (branch main): [{"id", "quando" (ISO com fuso), "video" (caminho na branch videos), "legenda", "status"}].
Para cada item vencido e pendente: baixa só aquele vídeo da branch "videos", envia pela API oficial e marca "publicado".
O token vem do segredo META_IG (JSON {"ig_user_id": "...", "ig_token": "..."}), nunca do repositório.
"""
import datetime as dt, json, os, subprocess, sys, time
import requests

G = "https://graph.facebook.com/v27.0"
AGENDA = "agenda.json"


def ok(r):
    if r.status_code >= 400:
        raise RuntimeError(f"Graph API {r.status_code}: {r.text[:300]}")
    return r.json()


def baixar(caminho):
    """Baixa só aquele vídeo da branch videos pela API do GitHub (arquivo até 100 MB)."""
    os.makedirs("_v", exist_ok=True)
    destino = os.path.join("_v", os.path.basename(caminho))
    r = requests.get(f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/contents/{caminho}", params={"ref": "videos"},
                     headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github.raw"}, stream=True, timeout=300)
    r.raise_for_status()
    with open(destino, "wb") as f:
        for bloco in r.iter_content(1 << 20): f.write(bloco)
    return destino


def publicar(video, legenda, cfg):
    tok, uid = cfg["ig_token"], cfg["ig_user_id"]
    c = ok(requests.post(f"{G}/{uid}/media", data={"media_type": "REELS", "upload_type": "resumable", "caption": legenda[:2200],
                                                    "share_to_feed": "true", "access_token": tok}))
    cid = c["id"]
    with open(video, "rb") as f:
        ok(requests.post(c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/v27.0/{cid}", data=f,
                         headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(os.path.getsize(video))}))
    for _ in range(60):
        st = ok(requests.get(f"{G}/{cid}", params={"fields": "status_code", "access_token": tok}))
        if st.get("status_code") == "FINISHED": break
        if st.get("status_code") == "ERROR": raise RuntimeError(f"Instagram recusou o vídeo: {st}")
        time.sleep(10)
    return ok(requests.post(f"{G}/{uid}/media_publish", data={"creation_id": cid, "access_token": tok}))["id"]


def main():
    cfg = json.loads(os.environ["META_IG"])
    agenda = json.load(open(AGENDA, encoding="utf-8"))
    agora = dt.datetime.now(dt.timezone.utc)
    mudou = False
    for it in sorted(agenda, key=lambda x: x["quando"]):
        if it.get("status") != "pendente": continue
        quando = dt.datetime.fromisoformat(it["quando"])
        if quando > agora: continue
        if (agora - quando).total_seconds() > 6 * 3600:  # passou muito da hora: não publica atrasado sem ninguém ver
            it["status"] = "atrasado"; mudou = True; continue
        try:
            it["media_id"] = publicar(baixar(it["video"]), it["legenda"], cfg)
            it["status"] = "publicado"; it["em"] = agora.isoformat()
            print(f"publicado: {it['id']}")
        except Exception as e:
            it["erro"] = str(e)[:300]; it["tentativas"] = it.get("tentativas", 0) + 1
            if it["tentativas"] >= 3: it["status"] = "erro"
            print(f"erro em {it['id']}: {it['erro']}", file=sys.stderr)
        mudou = True
    if mudou:
        json.dump(agenda, open(AGENDA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("nada vencido" if not mudou else "agenda atualizada")


if __name__ == "__main__":
    main()
